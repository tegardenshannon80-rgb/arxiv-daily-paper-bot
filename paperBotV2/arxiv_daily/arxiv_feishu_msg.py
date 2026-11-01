"""Deprecated compatibility entrypoint.

The upstream implementation hard-coded a private Feishu card template
(template_id=AAqxH62u1uNko), so it cannot work in a fresh tenant.
Use feishu_sender.py instead; this wrapper keeps the old module name working.
"""

from .feishu_sender import main

if __name__ == "__main__":
    raise SystemExit(main())
