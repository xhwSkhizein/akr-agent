import logging

logger = logging.getLogger(__name__)
import json
import os
from pydantic import Field
from typing import AsyncGenerator
from ..libs.search.duckduckgo import DuckDuckGoSearchAPIWrapper
from ..libs.search.tavily import TavilySearchAPIWrapper
from .base import Tool


class DuckDuckGoSearchTool(Tool):

    name: str = "search_duckduckgo"
    description: str = (
        "A tool around Duck Duck Go Search. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a search query. Output is a JSON array of the query results"
    )
    max_results: int = Field(alias="num_results", default=4)
    api_wrapper: DuckDuckGoSearchAPIWrapper = DuckDuckGoSearchAPIWrapper()
    backend: str = "text"

    async def run(self, keywords: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        Run search for a query through DuckDuckGo engine and return results.

        Args:
            keywords: Most related keywords to search for.

        Returns:
            A list of dictionaries with the following keys:
                snippet - The description of the result.
                title - The title of the result.
                link - The link to the result.
        """
        yield self.api_wrapper.run(keywords=keywords)


class TavilySearchTool(Tool):
    name: str = "search_tavily"
    description: str = (
        "A wrapper around Tavily Search. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a search query. Output is a JSON array of the query results"
    )
    max_results: int = 4
    api_wrapper: TavilySearchAPIWrapper = TavilySearchAPIWrapper(
        tavily_api_key=os.environ.get("TAVILY_API_KEY", None)
    )

    async def run(self, query: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        Run search for a query through TavilySearch engine and return results.

        Args:
            query: The query to search for.
        """
        logger.info(f"调用 Tavily Search， query={query}")
        try:
            raw_results = await self.api_wrapper.raw_results_async(
                query=query, max_results=self.max_results
            )
        except Exception as e:
            logger.error("调用 Tavily Search 失败，", e, stack_info=True)
            yield repr(e)
            return
        cleaned_results = self.api_wrapper.clean_results_with_images(raw_results)
        logger.info(
            "tavily search async, ",
            json.dumps(cleaned_results, indent=2, ensure_ascii=False),
            json.dumps(raw_results, indent=2, ensure_ascii=False),
        )
        yield cleaned_results
