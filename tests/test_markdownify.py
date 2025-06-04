import sys

try:
    import re
    import requests
    from markdownify import markdownify
    from requests.exceptions import RequestException

except ImportError:
    raise Exception("Required packages 'markdownify' and 'requests' are not installed")

MAX_LENGTH_TRUNCATE_CONTENT = 1000

def truncate_content(
    content: str, max_length: int = MAX_LENGTH_TRUNCATE_CONTENT
) -> str:
    if len(content) <= max_length:
        return content
    else:
        return (
            content[: max_length // 2]
            + f"\n..._This content has been truncated to stay below {max_length} characters_...\n"
            + content[-max_length // 2 :]
        )


def main(url: str) -> str:
    try:
        # Send a GET request to the URL with a 20-second timeout
        response = requests.get(url, timeout=20, headers={
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en,zh-CN;q=0.9,zh;q=0.8',
            'cache-control': 'max-age=0',
            'oai-did': 'a081b658-bad7-41f2-8ed0-28cf7975a6d7; ajs_anonymous_id=15d3da39-f27b-4ca6-ba02-7d606a81b9b5; intercom-id-dgkjq2bp=6236a5df-3fa1-45e6-bedd-b229178bb43b; intercom-device-id-dgkjq2bp=b24cd420-c14d-4d5d-98ff-0b6514d11609; _ga=GA1.1.471785481.1732446093; __stripe_mid=fffe2718-997f-4404-9b7a-807a2b9bf0929ef9b4; __stripe_mid=fffe2718-997f-4404-9b7a-807a2b9bf0929ef9b4; _ga_8MYC5SEFJ1=GS1.1.1735784365.10.0.1735784365.0.0.0; _ga_62J2E5SERF=GS2.1.s1747732581$o5$g1$t1747735176$j0$l0$h0; __cf_bm=tC6LR3_9rbxUm8Awd.evIh9bK_76Y31KMtyb1dkc00A-1748503882-1.0.1.1-KwH5HwHuDsvZvf9Qz1Lg_3jSY6h_xQyRX2tWyZa7.ymQfnEAReehybcyeYyTsAjWlNI3wwGgry4jSQnbaGtR2frukimWBWq..jCL4nxS7FA; _cfuvid=I58jukf4ZRxBd7sDA1LBF2O3KpeB5Kizt4yEvVJnmn8-1748503882122-0.0.1.1-604800000; cf_clearance=CJI73CKZOxWlrNA1XpPYSkkUohRR9.dtfYDta8Q9cic-1748503884-1.2.1.1-SYKOb671HEH8fNFi31kN6OBOC0p4MSdiwtCwVkoME.P7flfz7EKdXpzVkGr7vmhUmqDbWR9I8F4mgTHpJGx4UxnpdxDltyLSyvBh8_CDLbxW_G177YerqpArLtjC7NyZmLakQgSgxK8OaQa3ne6TIwz6oRhJ58MrGKT.ryew1CcMXvCZLFe8xEe31zND.HMpFL60Kl5EMf4cRIou490.sq63xnYriOJ8XxObGvMgy3cwxtXZK3FJ5GRl.wOcsqm1eVkNk642XJXK1RDsuxDWO7cGDecNeSfyY1RSxq7_KHvb9prngmkRu3J7FV8yTxUUMPIM0HFyGqtCDDplMyVGXjyiYCk7wZfbG2tjSpo.MeM; intercom-session-dgkjq2bp=; _dd_s=logs=1&id=0c098b66-0873-48c7-a256-ebf59742bb4d&created=1748503883294&expire=1748505083301',
            'priority': 'u=0, i',
            'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            'sec-ch-ua-mobile': '0',
            'sec-ch-ua-platform': 'macOS',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.3'
        })
        response.raise_for_status()

        # Convert the HTML content to Markdown
        print(response.text)
        markdown_content = markdownify(response.text).strip()

        # Remove multiple line breaks
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

        if not markdown_content:
            raise Exception("No content found in the webpage")

        return markdown_content

    except requests.exceptions.Timeout:
        raise Exception("The request timed out")
    except RequestException as e:
        raise Exception(f"Error fetching the webpage: {str(e)}")


if __name__ == "__main__":
    args = sys.argv
    if len(args) != 2:
        print("Usage: python test_markdownify.py <url>")
        sys.exit(1)
    url = args[1]
    print(main(url))
