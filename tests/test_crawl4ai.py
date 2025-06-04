import asyncio
from crawl4ai import *
from crawl4ai import content_filter_strategy
from crawl4ai.models import RunManyReturn
# from crawl4ai.markdown import DefaultMarkdownGenerator, BM25ContentFilter, PruningContentFilter


async def main():

    browser_config = BrowserConfig(
        verbose=True,
        headless=True,
        light_mode=True,
        proxy="http://127.0.0.1:7890",
    )  # Default browser configuration
    
    # content_filter = BM25ContentFilter(
    #     user_query="Anthropic",  # Optional query to focus the content
    #     bm25_threshold=1.0,                    # Minimum score threshold
    #     language="english"                     # Language for stemming
    # )
    content_filter = PruningContentFilter(threshold=0.4)
    
    # Create a markdown generator with a content filter
    md_generator = DefaultMarkdownGenerator(
        content_filter=content_filter,
        options={
            "body_width": 80,  # Wrap text at 80 characters
            "ignore_images": True,  # Skip images
            "single_line_break": True,  # Use single line breaks
        }
    )

    run_config = CrawlerRunConfig(
        # Content filtering
        word_count_threshold=10,
        excluded_tags=["form", "header"],
        exclude_external_links=True,
        # Content processing
        process_iframes=True,
        remove_overlay_elements=True,
        # Cache control
        cache_mode=CacheMode.ENABLED,  # Use cache if available)   # Default crawl run configuration
        markdown_generator=md_generator,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url="https://deepwiki.com/unclecode/crawl4ai/7.2-configuration-best-practices",
            config=run_config,
        )
        # Check success status
        print(result.success)  # True if crawl succeeded
        if not result.success:
            print(result.error)
            return
        # Different content formats
        # print(result.html)  # Raw HTML
        print("--==--" * 50)
        # print(result.cleaned_html)  # Cleaned HTML
        if result.markdown:
            print("--==--" * 50 + "\n RAW MARKDOWN\n")
            print(result.markdown.raw_markdown)  # Raw markdown from cleaned html
            print("--==--" * 50 + "\n FIT MARKDOWN\n")
            print(result.markdown.fit_markdown)  # Most relevant content in markdown

        


if __name__ == "__main__":
    asyncio.run(main())
