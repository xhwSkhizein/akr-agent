import logging

logger = logging.getLogger(__name__)
from ..libs.crawler.crawl4ai import Crawl4AIWrapper
from .base import Tool


class Crawl4AITool(Tool):
    name: str = "Crawl4AITool"
    description: str = (
        "A tool can crawl a website url then return a markdown text. "
        "Useful for when you need to answer questions about current events. "
        "Input should be a url. Output is a markdown text."
    )
    
    def __init__(self):
        super().__init__()
        self.wrapper = Crawl4AIWrapper()


    async def run(self, url: str, **kwargs) -> str:
        """
        Run crawl for a url and return markdown text.

        Args:
            url: The url to crawl.

        Returns:
            A markdown text.
        """
        return await self.wrapper.crawl(url=url)