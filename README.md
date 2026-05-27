# xiaozhi-python-client

need to copy libs folder from py-xiaozhi in order for opus.dll to be in the right place

https://github.com/huangjunsen0406/py-xiaozhi



ota.py to the initial 6-digit handshake with xiaozhi.me

query3.py to send query and get response(both text and audio)

query5.py sends query.pcm to xiaozhi.me

ffmpeg -i query.wav -ar 16000 -ac 1 -f s16le query.pcm