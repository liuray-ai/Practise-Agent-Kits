import re
from typing import Dict

class VariableEngine:
    """变量处理引擎"""
    
    def __init__(self):
        self.variable_pattern = re.compile(r'{{\s*(\w+)\s*}}')
    
    def replace_variables(self, template: str, variables: Dict) -> str:
        """
        替换模板中的变量
        
        Args:
            template: 包含 {{variable}} 语法的模板字符串
            variables: 变量映射字典
            
        Returns:
            替换后的字符串
        """
        def replace_match(match):
            var_name = match.group(1)
            return str(variables.get(var_name, match.group(0)))
        
        return self.variable_pattern.sub(replace_match, template)
    
    def extract_variables(self, template: str) -> set:
        """
        从模板中提取所有变量名
        
        Args:
            template: 模板字符串
            
        Returns:
            变量名集合
        """
        return set(self.variable_pattern.findall(template))