import requests
import os
from xml.etree.ElementTree import XML

class RssFeedLoader:
    def __init__(self, rss_file='rss_feed.txt'):
        self.rss_file = rss_file

    def on_user_input_done(self, user_input, verbose_mode=False):
        return None
    
    def get_news(self, category=None):
        # category is not used in this example
        return self.get_content()
    
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': 'get_news',
                'description': 'Get news from RSS feeds',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'category': {
                            'type': 'string',
                            'description': 'The category of news to fetch',
                        }
                    }
                }
            }
        }

    def load_urls(self):
        # Check if the file exists, if not, append filename to the current script location
        if not os.path.exists(self.rss_file):
            self.rss_file = os.path.join(os.path.dirname(__file__), self.rss_file)

        if not os.path.exists(self.rss_file):
            print(f"RSS file not found: {self.rss_file}")
            return []

        try:
            with open(self.rss_file, 'r') as file:
                urls = [line.strip() for line in file.readlines()]
            return urls
        except Exception as e:
            print(f"Error reading the RSS file: {e}")
            return []

    def load_feed(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an error for bad status codes
            return response.text
        except Exception as e:
            print(f"Error loading the RSS feed from {url}: {e}")
            return None

    def parse_feed(self, xml_content):
        root = XML(xml_content)
        channel = root.find('channel')
        if not channel:
            return []

        items = channel.findall('item')
        feed_items = []
        for item in items:
            title = item.find('title').text or 'No Title'
            link = item.find('link').text or 'No Link'
            summary = item.find('description').text or 'No Summary'
            feed_items.append({
                'title': title,
                'link': link,
                'summary': summary
            })
        return feed_items

    def parse_feeds(self):
        urls = self.load_urls()
        feeds = []
        for url in urls:
            xml_content = self.load_feed(url)
            if xml_content:
                feed_items = self.parse_feed(xml_content)
                if feed_items:
                    feeds.append({
                        'url': url,
                        'items': feed_items
                    })
        return feeds

    def get_content(self):
        feeds = self.parse_feeds()
        content = []
        for feed in feeds:
            for item in feed['items']:
                content.append(item)
        return content