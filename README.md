sendf is a program used to easily send one file to another person.

sendf file [files ...]

It will run a HTTP server in the background, and give you a link for the file.
The link expires in 30 minutes.
Directories are supported as well.
If a folder is specified and/or multiple files are specified, they will be
tarred and compressed before being sent as archive.tgz.

The file will NOT be saved in the cloud. The file is tranferred directly from
your computer to the other person's computer.

For a full list of options, type
sendf -h

This program will automatically forward ports using UPnP. If you are behind a
router without UPnP, it will probably not work.

This program does depend on CherryPy, which you can install through pip.

This program is released under the BSD license.
It does depend on a UPnP component from the Tribler project, which itself is
released under the LGPL license.
