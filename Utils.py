"""Utility classes for JSON processing and message handling."""
import json
import re
import logging
from typing import Optional, Any, Union

class JSONFixer:
    """
    Class for fixing malformed JSON strings by correcting common issues.
    """
    
    @staticmethod
    def fix_json_string(malformed_json: Union[str, bytes]) -> Optional[dict]:
        """
        Attempts to fix malformed JSON by correcting common issues.
        
        Args:
            malformed_json: The malformed JSON string or bytes to fix
            
        Returns:
            Optional[dict]: Parsed JSON dictionary if successful, None if failed
        """
        try:
            if isinstance(malformed_json, bytes):
                malformed_json = malformed_json.decode()
                
            malformed_json = malformed_json.replace("'", "\"")
            malformed_json = re.sub(r'(?<!")\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?!")\s*:', r'"\1":', malformed_json)
            malformed_json = re.sub(r'(\s*"\w+"\s*:\s*[^,{[\]]+)\s+("\w+"\s*:\s*)', r'\1, \2', malformed_json)
            malformed_json = re.sub(r'(\s*"[^"]+"\s*)(?=\s*"[^"]+")', r'\1,', malformed_json)
            
            if not malformed_json.startswith("{"):
                malformed_json = "{" + malformed_json
            if not malformed_json.endswith("}"):
                malformed_json = malformed_json + "}"
                
            return json.loads(malformed_json)
        except Exception as e:
            logging.error(f"JSON fix failed: {e}")
            return None
