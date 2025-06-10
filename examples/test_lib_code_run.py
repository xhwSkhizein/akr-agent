from akr_agent.libs.code.code_exec import PythonCodeExecutor
from typing import Union, List


def realtime_web_search(query: Union[str, List[str]]) -> str:
    """Searches the web for the given query and returns the results."""
    from akr_agent.libs.search.tavily import TavilySearchAPIWrapper
    import os
    import json
    wrapper = TavilySearchAPIWrapper(tavily_api_key=os.environ.get("TAVILY_API_KEY", None))
    if isinstance(query, list):
        results = [wrapper.results(q, max_results=2) for q in query]
    else:
        results = wrapper.results(query, max_results=3)
    results = [result for result in results if result.get("content")]
    final_result = json.dumps(results, indent=2, ensure_ascii=False)

    return final_result


def web_crawler_to_markdown(url: Union[str, List[str]]) -> str:
    """Crawls the given URL and returns the content as Markdown."""
    import asyncio
    from akr_agent.libs.crawler.crawl4ai import Crawl4AIWrapper
    wrapper = Crawl4AIWrapper()
    if isinstance(url, list):
        results = [asyncio.run(wrapper.crawl(u)) for u in url]
        result = "\n\n".join(results)
    else:
        result = asyncio.run(wrapper.crawl(url))
    
    return result



executor = PythonCodeExecutor()
code_text = """
import json
def search_best_llm():
    try:
        leaderboard_info = realtime_web_search(query="Hugging Face Open LLM Leaderboard current top models")
        recent_reviews = realtime_web_search(query="best open source LLM May 2024 review OR Llama 3 vs Mixtral vs Qwen")
        return {
            "leaderboard_info": leaderboard_info,
            "recent_reviews": recent_reviews
        }
    except Exception as e:
        return {"error": str(e)}

search_results = search_best_llm()
search_results
"""
result = executor.run(code_text, realtime_web_search=realtime_web_search, web_crawler_to_markdown=web_crawler_to_markdown)

print("--==--" * 10)
print("\n\n")
for k, v in result.items():
    print(f"{k}: {v}")






SYSTEM_PROMPT = """
You are the best coding assistant assigned with the task of problem-solving.
Follow a structured approach to problem-solving by outlining your plan, implementing it in code, executing it, and presenting the final solution.

# Steps

1. **Thinking Process:** 
   - Provide a complete, step-by-step outline of your plan to solve the provided problem.
   - Detail all the necessary steps you will take, considering constraints.

2. **Code Implementation:** 
    - Based on your detailed thinking process, write the complete Python code required to execute the plan and work towards the solution.
3. **Execution Block:** 
    - Enclose the complete code you wrote in Step 2 within <execute>...</execute> tags.
    - Make sure the last line of the code is the variable name you want to return.
    - *(Note: After you provide the thinking process and the code in the <execute> block, the environment will execute the code and provide its output back to you.)*
4. **Execution Result Analysis:**    
    - Analyze the output from the execution environment. If result solve the problem, Provide the final answer or required output within <solution>...</solution> tags.
    - If result does not solve the problem, analyze the error and step back to the thinking process and code implementation.
5. **Final Solution:** 
    - After reviewing the output from the execution environment, process the results and provide the final answer or required output within <solution>...</solution> tags.


# Constraints and Usage Rules:

* You have only one opportunity to interact with the execution environment using the `<execute>` tag.
* The `<solution>` tag should be used only once at the end of the process to deliver the final result based on the code execution output.
* You python code should only use the tools provided by the environment and built-in python packages.


# Available Tools:

* realtime_web_search(query_list: List[str]) -> str
> This tool provides access to real-time online information. Use it to retrieve the most recent information you need.

* web_crawler_to_markdown(url_list: List[str]) -> str
> This tool allows you to crawl multiple urls and retrieve their content. Use it to extract information from multiple websites.
"""