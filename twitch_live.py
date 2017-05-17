import os
import re
import sys
import m3u8
import time
import requests
import queue
import threading
import shutil

# get your own client id by registering to twitch
headers = {
    'Client-ID': ''
}

if not headers['Client-ID']: exit('No Client-ID provided')

usher_url   = 'http://usher.twitch.tv/api/channel/hls/{channel}.m3u8'
token_url   = 'http://api.twitch.tv/api/channels/{channel}/access_token'
kraken_url  = 'https://api.twitch.tv/kraken/streams/{channel}'

# remove windows filename unfriendly stuff
def sanitize(s):
    rx = '[' + re.escape(''.join(['\/<>:|*"?'])) + ']'
    return re.sub(rx, '', s)

# thread for downloading segment
class Downloader(threading.Thread):
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self._queue = queue
        
    def run(self):
        while True:
            segnum, uri = self._queue.get()
            r = requests.get(uri, stream=True)
            self.filepath = os.path.join('tmp', '%d.mp4' % segnum)
            with open(self.filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk: f.write(chunk)
                    else: break
            self._queue.task_done()

if len(sys.argv) < 2: exit('No channel provided')
channel = sys.argv[1]

# get stream info
r = requests.get(kraken_url.format(channel=channel), headers=headers)
j = r.json()

if not j['stream']: exit('No stream online')

# filename generation
timestamp   = time.strftime('%y%m%d-%H%M%S')
status      = sanitize(j['stream']['channel']['status'])
game        = sanitize(j['stream']['channel']['game'])
filename    = '%s %s - %s (%s).mp4' % (timestamp, channel, status, game)
filepath    = os.path.join('dump', filename)

# directories
for dir in ('tmp', 'dump'):
    if not os.path.exists(dir):
        os.makedirs(dir)

# access token
r = requests.get(token_url.format(channel=channel), headers=headers)
j = r.json()
params = {
    'player':           'twitchweb',
    'type':             'any',
    'allow_source':     'true',
    'allow_audio_only': 'true',
    'allow_spectre':    'false',
    'token':            j['token'],
    'sig':              j['sig']
}
r = requests.get(usher_url.format(channel=channel), params=params)
m3u8_obj = m3u8.loads(r.text)

# get the best quality stream
uri = None
prev_bandwidth = 0
for p in m3u8_obj.playlists:
    bandwidth = p.stream_info.bandwidth / 1024
    if bandwidth > prev_bandwidth:
        uri = p.uri
        prev_bandwidth = bandwidth

if not uri: exit('No stream found')

# workers
queue = queue.Queue()
for i in range(5):
    downloader = Downloader(queue)
    downloader.setDaemon(True)
    downloader.start()

# playlist iteration
last_segnum = 0
while True:
    m3u8_obj = m3u8.load(uri)
    if not m3u8_obj: break
    
    for seg in m3u8_obj.segments:
        segnum = int(seg.uri.split('-')[1].split('-')[0])
        # dismiss segments that are already downloaded
        if segnum > last_segnum:
            queue.put((segnum, seg.absolute_uri))
            last_segnum = segnum
        
    if queue.qsize():
        # download segments
        queue.join()
        # join the segments
        with open(filepath, 'ab') as f:
            for tmp in os.listdir('tmp'):
                tmp_path = os.path.join('tmp', tmp)
                shutil.copyfileobj(open(tmp_path ,'rb'), f)
                os.remove(tmp_path)
    
    # sleep for a while
    time.sleep(m3u8_obj.target_duration)