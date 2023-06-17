# For futures and thread pool executors
import concurrent.futures
# To make GET Requests
import requests
# To turn returned text -> parsable HTML
from bs4 import BeautifulSoup
# For mutexes
from threading import Lock
# For URL Parsing
from urllib.parse import urlparse
# For a queue to wait for task completion
from queue import Queue
# To catch SIGINT/CTRL+C
import signal
# For Dict -> JSON
import json 

# If CTRL+C is hit, we will flip this to 
# false, which will kill our threads cleanly
RUNNING = True

class LockingDict(dict):
    """A locking dict which locks a mutex on insertions / settings
    """
    def __init__(self):
        self.lock = Lock()
        super().__init__()

    def __setitem__(self, key, value):
        with self.lock:
            super().__setitem__(key, value)
        
class MyScraper(object):
    """A web scraper / crawler

    Attributes:
        1. executor - our concurrent threadpool executor which we will submit tasks to
        2. start_urls - The URLs we want to start our crawling at
        3. max_recursion_depth - How many iterations should we crawl
        4. output - an optional output file to write results to
        5. futures - a queue of futures which we will wait for completion
        6. data - our raw data from the webscraper
    """
    def __init__(self, start_urls = [], max_workers = 5, max_recursion_depth = 5, output = 'stdout'):
        self.executor            = concurrent.futures.ThreadPoolExecutor(max_workers = max_workers)
        self.start_urls          = start_urls
        self.max_recursion_depth = max_recursion_depth
        self.output              = output
        self.futures             = Queue()
        self.data                = LockingDict()

    def scrape(self):
        """Starts the scraping process for each start_url

        Each executor may kick off more futures, which causes a 
        spidering-out of searching on the web
        """

        # 1. Start each executor and save them in our queue
        for url in self.start_urls:
            self.futures.put(self.executor.submit(self.__scrape, url, 0))
        
        # 2. Do a sanity check to make sure all futures have finished
        #    This will run until either the max recursion is hit or the
        #    user issues a ctrl+c
        self.__drain_queue()

        # 4. Dumps the results to either stdout or a file
        jsonified = json.dumps(self.data, indent=4)
        if self.output == 'stdout':
            print(jsonified)

        else:
            with open(self.output, 'w') as f:
                f.write(jsonified)
        
    def __scrape(self, url, depth):
        """The function which the futures will invoke

        Arguments:
            1. url - the url to search
            2. depth - the current depth of this future

        Returns:
            1. ID - a url + depth ID which indicates which URL
                    was searched at which depth 
        """

        # if a user has hit ctrl+x, RUNNNING will be false
        # and we will stop calling more futures
        if RUNNING:     
        
            # If we are at max depth, we will stop calling more futures
            # If this URL has been searched, no need to search it again
            if url not in self.data and depth < self.max_recursion_depth:
                try:
                    r = requests.get(url)

                # if the request fails, we will print the error and return
                except Exception as e:
                    print(str(e))
                    return f"{url}-{depth}"
                
                # If the get mwas successful, lets parse the HTML and save
                # it to our data dict
                if r.ok:
                    data = dict()
                    soup = BeautifulSoup(r.text, 'html.parser')
                    data['raw'] = soup.prettify()
                    data['headers'] = [str(s) for s in soup.find_all('h1')]
                    self.data[url] = data
                    for link in soup.find_all('a', href=True):
                        next_url = link['href']
                        
                        # handle relative URLs in hrefs
                        if next_url.startswith("/"):
                            current_url_parsed = urlparse(url)
                            next_url = current_url_parsed.scheme + "://" + current_url_parsed.netloc + "/" + next_url

                        # Call the next future
                        self.futures.put(self.executor.submit(self.__scrape, next_url, depth + 1))

            else:
                print("URL searched or max recursion hit! Returning...")
        else:
            print("Running set to false! Returning...")
        return f"{url}-{depth}"

    def __drain_queue(self):
        while not self.futures.empty():
            print(self.futures.get().result())
            
def kill_threads(sig, frame):
    global RUNNING
    print('You pressed Ctrl+C!')
    RUNNING = False
        
def main():
    signal.signal(signal.SIGINT, kill_threads)
    s = MyScraper(start_urls = ['https://www.zyte.com/blog/'], max_recursion_depth = 2, output = 'test.json')
    s.scrape()

if __name__ == "__main__":
    main()