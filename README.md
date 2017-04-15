sendf is a program used to send one or more files to another person.

```
sendf file [files ...]
```

It will run a HTTP server in the background, and give you a link for the file.
If a folder is given and/or multiple files are given, a tarred and compressed archive of the files will sent.
Files are NOT be saved in the cloud. The file is tranferred directly from your computer to the other person's computer.

For a full list of options, type
```
sendf -h
```

This program can automatically forward ports using UPnP if your router supports UPnP.

This program is released under the BSD license.
