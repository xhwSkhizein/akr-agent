import asyncio
import logging
from crawl4ai import *
from crawl4ai import content_filter_strategy
from crawl4ai.models import RunManyReturn


class Crawl4AIWrapper(BaseModel):
    """Wrapper for Crawl4AI"""

    browser_config: BrowserConfig
    run_config: CrawlerRunConfig

    def __init__(self):
        self.browser_config = BrowserConfig(
            verbose=False,
            headless=True,
            light_mode=True,
            # proxy="http://127.0.0.1:7890",
        )  # Default browser configuration

        self.content_filter = PruningContentFilter(threshold=0.4)
        # Create a markdown generator with a content filter
        self.md_generator = DefaultMarkdownGenerator(
            content_filter=self.content_filter,
            options={
                "body_width": 88,  # Wrap text at 80 characters
                "ignore_images": True,  # Skip images
                "single_line_break": True,  # Use single line breaks
            },
        )
        self.run_config = CrawlerRunConfig(
            # Content filtering
            word_count_threshold=10,
            excluded_tags=["form", "header"],
            exclude_external_links=True,
            # Content processing
            process_iframes=True,
            remove_overlay_elements=True,
            # Cache control
            cache_mode=CacheMode.ENABLED,  # Use cache if available)   # Default crawl run configuration
            markdown_generator=self.md_generator,
        )

    async def crawl(self, url: str):
        async with AsyncWebCrawler(config=self.browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=self.run_config,
            )
            # Check success status
            if not result.success:
                logging.error(result.error)
                return ""

            # print(result.cleaned_html)  # Cleaned HTML
            if result.markdown:
                logging.info("--==--" * 50 + "\n RAW MARKDOWN\n")
                logging.info(
                    result.markdown.raw_markdown
                )  # Raw markdown from cleaned html
                logging.info("--==--" * 50 + "\n FIT MARKDOWN\n")
                logging.info(
                    result.markdown.fit_markdown
                )  # Most relevant content in markdown
                return (
                    result.markdown.fit_markdown
                    if result.markdown.fit_markdown
                    else result.markdown.raw_markdown
                )

            else:
                return result.cleaned_html


if __name__ == "__main__":
    wrapper = Crawl4AIWrapper()
    asyncio.run(
        wrapper.crawl(
            url="https://deepwiki.com/unclecode/crawl4ai/7.2-configuration-best-practices"
        )
    )
