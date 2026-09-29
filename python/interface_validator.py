    return self.do_open(http.client.HTTPConnection, req)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/urllib/request.py", line 1348, in do_open
    h.request(req.get_method(), req.selector, req.data, headers,
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/http/client.py", line 1351, in request
    self._send_request(method, url, body, headers, encode_chunked)
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/http/client.py", line 1362, in _send_request
    self.putrequest(method, url, **skips)
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/http/client.py", line 1196, in putrequest
    self._validate_path(url)
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/http/client.py", line 1296, in _validate_path
    raise InvalidURL(f"URL can't contain control characters. {url!r} "
http.client.InvalidURL: URL can't contain control characters. '/tgyg/lib/红果短剧最终版 (1).py' (found at least ' ')
Error: Process completed with exit code 1.
