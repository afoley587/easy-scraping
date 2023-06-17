# Learning By Example: Python Webscraping With Concurrency

## Motivation

## The Code

Let's go over the design of our system. We will have some web-scraper
parent class which will start a bunch of concurrently running futures
to actually do the work. It will then store a handle to each future in
a queue so that we can wait for all of our futures to stop processing before
killing the program. We will then store all of the results from the futures
in a huge thread-safe dictionary which we can write to a file as JSON or dump
it to STDOUT.

The futures themselves are also extremely important, as they will be doing
the bulk of the work for this program. They will make a simple GET request to
some URL passed to them. It will then look in the contents from that GET request
and find any links that it can. For each link it finds, it's going to create a NEW
future that will do the same process over and over. This is how we achieve the
"Spidering" or "Crawling" functionality which traverses hundreds of web pages.

Without further adieu, let's get into the code! It'll be less than 140 lines
(even with comments), so this will be quick! But, if you're antsy, feel free to 
jump to my GitHub repo which is linked below.

So, we're going to start with our imports and global variables:

```python
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
```

The imported libraries should be self-explanatory. However, the global `RUNNING`
flag might not be. If a user wants to end the web-scraping early, they may hit 
`CTRL+C`. We want to make sure that our futures cleanly exit in this case and
that any cleanup operations (like saving data) can occur. So, if a user does
hit `CTRL+C`, we will catch that, flip `RUNNING` to false, and then let the cleanup
operations happen.

Next, we will create a thread-safe dictionary for our piece-of-mind:

```python
class LockingDict(dict):
    """A locking dict which locks a mutex on insertions / settings
    """
    def __init__(self):
        self.lock = Lock()
        super().__init__()

    def __setitem__(self, key, value):
        with self.lock:
            super().__setitem__(key, value)
```

Note that this dictionary is almost the same as any basic python `dict()`. The
only difference is that when someone is going to set an item in the dictionary
with the `[]` syntax (i.e. `this[thing] = 'that'`), we will hold a lock so that
two threads don't try to make changes at the same time. This is the object type that
we will use to hold data from executed futures.

Finally, we can get into our web-scraper! Lets go method-by-method:

### __init__

Let's look at the simple `__init__` below:

```python
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
```

In this `__init__`, we are creating:

1. a new `ThreadPoolExecutor` so that we can submit new futures for scraping 
    to it
2. We will also have a set of `start_urls` which tell our executor which URLs 
    to use as a starting point
3. We set a `max_recursion_depth` to tell our futures when they should stop spawning
    new futures
4. We set some `output` file or `stdout`
5. We create a queue to put all of our `futures` in
6. Finally, we create a new thread-safe `LockingDict` to put all of our data in

Next, we need some entrypoint in our parent class to kick off our web-scraping:

```python
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
```

So, the first thing we do is start a new future for each url in our starting
urls. This will kick off the web-crawling, and we will see the `__scrape` method 
in a few seconds. For now, let's just envision that it's going to start a whole
bunch of web-scraping. Next, we will use the `__drain_queue` method to
wait for all of our futures to either hit the `max_recursion_depth` or 
for some user to hit `CTRL+C`. Finally, we will dump all of our data to either
`stdout` or some file.

So, let's dive into the `__scrape` method since it does almost all of the work:

```python
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
```

The first thing we do is check our global `RUNNING` flag. As previously said,
if someone hits `CTRL+C`, we will set this to false. This is how we cleanly
exit our futures and avoid them from spawning more futures. Next, we double check
two things:

1. Have I searched this URL before? If so, I don't need to check it again. This
    helps avoid circular links
2. Am I at my max recursion depth? If so, I need to stop here

After our pre-checks, we make our GET request to the passed URL. We can then use
`BeautifulSoup` to turn the returning HTML into a nice and parsable python format
and we save the raw HTML and the headers into our data dictionary. You can add
any filters you want in here! Finally, we look for all of the links in our returned
HTML by searching for `hrefs`. For each link we find, let's spawn another future to
repeat the same process over and over again.

I'll briefly touch on the `__drain_queue` method as well since we previously mentioned
it:

```python
    def __drain_queue(self):
        while not self.futures.empty():
            print(self.futures.get().result())
```

Note that every future we submit to our executor gets `put` into our `self.futures` queue.
So this `__drain_queue` method will just wait until that queue is empty before returning.
If its not empty, it'll use the `Queue.get()` method to wait for the next tasks
completion. This allows our program to wait for all future completion before exiting.

Lastly, we need two more methods outside of this class:

1. Something to set our `RUNNING` flag to false. We will call this `kill_threads`.
2. Something to actually start our web-scraper. We will call this `main`

```python
def kill_threads(sig, frame):
    global RUNNING
    print('You pressed Ctrl+C!')
    RUNNING = False
        
def main():
    signal.signal(signal.SIGINT, kill_threads)
    s = MyScraper(start_urls = ['https://www.zyte.com/blog/'], max_recursion_depth = 2, output = 'test.json')
    s.scrape()
```

So the `kill_threads` method just sets `RUNNING` to false - easy! The `main` method
will issue a callback so that if `CTRL+C` is hit, which sends a `SIGINT` signal, the 
`kill_threads` method is called.

`main` then just goes through and instantiates a scraper with some urls, some 
recursion depth, and some output file. It then begins its scraping!

## Running
The requirements are hosted in the GitHub repo in the `requirements.txt` file. After
installing, you can run with 

```shell
prompt> python easy_scraping/customscraper.py
.
.
.
.
.
https://www.zyte.com//resources/-2
https://www.zyte.com//learn/-2
https://www.zyte.com//blog/-2
https://www.zyte.com//meet-zyte/-2
https://www.zyte.com//jobs/-2
https://www.zyte.com//terms-policies/-2
https://support.zyte.com/-2
https://www.zyte.com//contact-us/-2
https://www.zyte.com//?page_id=7190-2
https://help.twitter.com/using-twitter/twitter-supported-browsers-2
https://twitter.com/tos-2
https://twitter.com/privacy-2
https://support.twitter.com/articles/20170514-2
https://legal.twitter.com/imprint.html-2
https://business.twitter.com/en/help/troubleshooting/how-twitter-ads-work.html?ref=web-twc-ao-gbl-adsinfo&utm_source=twc&utm_medium=web&utm_campaign=ao&utm_content=adsinfo-2
prompt>
```

Note that you will get a lot of output and the URLs may vary! There will be a 
`test.json` file in the same directory with your web scraping results!

## GitHub
