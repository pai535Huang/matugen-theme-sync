#!/usr/bin/env python3
"""Ask the terminal for its live background colour (OSC 11).

Prints "#rrggbb" on success. Exit codes tell the caller what went wrong:

    0  answered
    2  no controlling terminal (/dev/tty could not be opened)
    3  the terminal never answered the query
    4  the terminal answered with something that is not an OSC 11 colour

Note that not every terminal answers OSC 11; a terminal that does not support
it looks the same as one that is simply not processing input.
"""

import os
import re
import select
import sys
import termios
import tty

QUERY = b"\x1b]11;?\x1b\\"
DEFAULT_TIMEOUT = 1.5

EXIT_OK = 0
EXIT_NO_TTY = 2
EXIT_NO_REPLY = 3
EXIT_UNPARSABLE = 4

COLOUR = re.compile(rb"rgb:([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})")


def ask(fd, timeout):
    """Send the query and collect the terminal's reply."""
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        os.write(fd, QUERY)
        buf = b""
        deadline = os.times().elapsed + timeout
        while os.times().elapsed < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            chunk = os.read(fd, 128)
            if not chunk:
                break
            buf += chunk
            if b"\x1b\\" in buf or b"\x07" in buf:
                break
        return buf
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def parse(buf):
    """Turn an OSC 11 reply into #rrggbb, or None."""
    match = COLOUR.search(buf)
    if match is None:
        return None
    channels = []
    for raw in match.groups():
        text = raw.decode("ascii").lower()
        # 4-digit channels are 16 bit per channel; keep the high byte.
        channels.append(text[:2] if len(text) == 4 else text)
    return "#" + "".join(channels)


def main(argv):
    timeout = DEFAULT_TIMEOUT
    if len(argv) > 2 and argv[1] == "--timeout":
        try:
            timeout = float(argv[2])
        except ValueError:
            print("--timeout needs a number", file=sys.stderr)
            return EXIT_UNPARSABLE

    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError as exc:
        print(f"no controlling terminal: {exc}", file=sys.stderr)
        return EXIT_NO_TTY

    try:
        buf = ask(fd, timeout)
    finally:
        os.close(fd)

    if not buf:
        print(
            "no OSC 11 reply from the terminal within %.1fs" % timeout,
            file=sys.stderr,
        )
        return EXIT_NO_REPLY

    colour = parse(buf)
    if colour is None:
        print("unparsable OSC 11 reply: %r" % buf, file=sys.stderr)
        return EXIT_UNPARSABLE

    print(colour)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
