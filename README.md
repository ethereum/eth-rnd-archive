# Eth R&D Discord Archive

This is a human and machine readable archive of all discussions in the Eth R&D Discord.

## Structure and Format

- One directory per Discord channel
- Each directory will contain JSON files for each day there was activity in the channel named `YYYY-MM-DD.json`

Format of the files:

```
[
    {
        "author": "<Discord username of the author>",
        "category": "<Discord channel category>",
        "parent": "<Channel parent if this message belongs to a thread>",
        "content": "<The actual message content>",
        "created_at": "<ISO8601 timestamp of the message>",
        "attachements": [
            {
                "type": "<mime type of the attachement>",
                "origin_name": "<original name of the attached file>",
                "content": "<base64 encoded bytes of the attachement>"
            }
        ]
    }
]
```

## Updates

The archive is updated once a week by EF DevOps.

## Known limitations

- GIFs from discord are not captured. Messages with only a GIF will be empty
- Emoji reactions are not captured
- Threads might not be correctly exported atm


