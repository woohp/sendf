sendf sends file(s) to another person through the browser.

[![Build Status](https://github.com/woohp/sendf/actions/workflows/ci.yml/badge.svg)](https://github.com/woohp/sendf/actions)

```
sendf file [files ...]
```

It will run an HTTP server in the foreground and give you a link for the file.
If a folder or multiple files are given, an uncompressed tar archive will be sent.
Files are NOT be saved in the cloud. The file is tranferred directly from your computer to the other person's computer.

For a full list of options, type
```
sendf -h
```

This program can automatically forward ports using UPnP if your router supports UPnP.

This program is released under the BSD license.
