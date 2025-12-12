"""
Twitter publisher - publishes tweets to Twitter
"""
import time
from typing import Callable, List, Optional

import tweepy
from tweepy.errors import TooManyRequests

from utils import get_logger

logger = get_logger("TwitterPublisher")


class TwitterPublisher:
    """Publishes content to Twitter"""
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_secret: str,
        bearer_token: str = None
    ):
        # Initialize Twitter API v2 client
        self.client = tweepy.Client(
            bearer_token=bearer_token,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret
        )
        
        # Initialize API v1.1 for media upload
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
        self.api_v1 = tweepy.API(auth)
        self._rate_limit_max_retries = 4
        self._rate_limit_min_wait = 5  # seconds
        self._rate_limit_max_wait = 300  # seconds

    def _execute_with_rate_limit(
        self,
        action: str,
        func: Callable,
        *args,
        **kwargs,
    ):
        """Execute a Twitter request, retrying when hitting rate limits."""
        for attempt in range(1, self._rate_limit_max_retries + 1):
            try:
                return func(*args, **kwargs)
            except TooManyRequests as error:
                wait_seconds = self._calculate_wait_time(error, attempt)
                self._log_rate_limit_headers(error, action)

                if attempt == self._rate_limit_max_retries:
                    logger.error(
                        f"Rate limit hit for {action} and retries exhausted, giving up."
                    )
                    raise

                logger.warning(
                    f"Rate limit hit for {action} (attempt {attempt}/{self._rate_limit_max_retries}). "
                    f"Waiting {wait_seconds:.1f}s before retry."
                )
                time.sleep(wait_seconds)
            except Exception:
                raise

    def _calculate_wait_time(self, error: TooManyRequests, attempt: int) -> float:
        """Determine how long to wait before retrying after 429."""
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        reset_ts = headers.get("x-rate-limit-reset")

        if reset_ts:
            try:
                reset_seconds = int(reset_ts) - int(time.time())
                if reset_seconds > 0:
                    return min(max(reset_seconds, self._rate_limit_min_wait), self._rate_limit_max_wait)
            except (TypeError, ValueError):
                pass

        # Fallback to exponential backoff (5s, 10s, 20s, ...)
        wait_seconds = self._rate_limit_min_wait * (2 ** (attempt - 1))
        return min(wait_seconds, self._rate_limit_max_wait)

    def _log_rate_limit_headers(self, error: TooManyRequests, action: str) -> None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        limit = headers.get("x-rate-limit-limit")
        remaining = headers.get("x-rate-limit-remaining")
        reset = headers.get("x-rate-limit-reset")

        logger.warning(
            f"Twitter rate limit details for {action} - limit: {limit}, remaining: {remaining}, reset: {reset}"
        )
    
    def post_tweet(self, text: str, media_path: Optional[str] = None) -> Optional[str]:
        """
        Post a single tweet
        
        Args:
            text: Tweet text (max 280 characters)
            media_path: Optional path to image/video to attach
            
        Returns:
            Tweet ID if successful, None otherwise
        """
        try:
            media_id = None
            if media_path:
                media = self.api_v1.media_upload(media_path)
                media_id = media.media_id
            
            response = self._execute_with_rate_limit(
                "create_tweet",
                self.client.create_tweet,
                text=text,
                media_ids=[media_id] if media_id else None,
            )
            
            tweet_id = response.data['id']
            logger.info(f"Posted tweet: {tweet_id}")
            return tweet_id
            
        except TooManyRequests:
            logger.error("Failed to post tweet due to repeated rate limits.")
            return None
        except Exception as e:
            logger.error(f"Failed to post tweet: {e}")
            return None
    
    def post_thread(self, tweets: List[str]) -> List[str]:
        """
        Post a Twitter thread
        
        Args:
            tweets: List of tweet texts
            
        Returns:
            List of tweet IDs
        """
        tweet_ids = []
        previous_tweet_id = None
        
        for i, tweet_text in enumerate(tweets):
            try:
                response = self._execute_with_rate_limit(
                    "create_tweet_thread",
                    self.client.create_tweet,
                    text=tweet_text,
                    in_reply_to_tweet_id=previous_tweet_id,
                )
                
                tweet_id = response.data['id']
                tweet_ids.append(tweet_id)
                previous_tweet_id = tweet_id
                
                logger.info(f"Posted tweet {i+1}/{len(tweets)}: {tweet_id}")
                
            except TooManyRequests:
                logger.error("Rate limit hit while posting thread; aborting further tweets.")
                break
            except Exception as e:
                logger.error(f"Failed to post tweet {i+1}: {e}")
                break
        
        return tweet_ids
    
    def delete_tweet(self, tweet_id: str) -> bool:
        """Delete a tweet"""
        try:
            self._execute_with_rate_limit(
                "delete_tweet",
                self.client.delete_tweet,
                tweet_id,
            )
            logger.info(f"Deleted tweet: {tweet_id}")
            return True
        except TooManyRequests:
            logger.error("Rate limit hit while deleting tweet %s; delete aborted.", tweet_id)
            return False
        except Exception as e:
            logger.error(f"Failed to delete tweet {tweet_id}: {e}")
            return False
