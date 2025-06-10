

from .langfun_python_code import PythonCode
from .langfun_correction import CodeWithError, CorrectedCode

def fix_code_error_by_llm(code_with_error: CodeWithError):
    """Fixes the code by using a language model."""
    
    code_text = code_with_error.code
    error = code_with_error.error
    
    prompt = """Given the following code and error:
    Code:
    ```python
    {code}
    ```
    
    Error:
    {error}
    
    Fix the code and return the final corrected code only.
    """
    # TODO: use llm to fix the code
    # result = llm.invoke(prompt.format(code=code_text, error=error))
    
    return CorrectedCode(corrected_code=code_text)

class PythonCodeExecutor:
    def __init__(self):
        pass

    def run(self, code_text: str, **kwargs):
        code = PythonCode(source=code_text)
        result = code(
            sandbox=False,
            timeout=30,
            autofix=3,
            outputs_intermediate=True,
            returns_stdout=False,
            fix_code_error_by_llm=fix_code_error_by_llm,
            global_vars={
                **kwargs
            },
            **kwargs,
        )
        return result