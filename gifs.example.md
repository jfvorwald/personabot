# The GIF pool

Copy this to `gifs.md` and fill it with links. That file is gitignored, because
a list of what a particular group finds funny is as personal as the persona is.

There is no search API behind this. Tenor's shut down and Discord's picker is
not callable by a bot, but the bigger reason is that **a bad GIF is far more
conspicuous than no GIF** - a reaction that nearly fits reads worse than words,
because everyone can see what was being aimed at. Searching a public index
gambles on that every time. A pool you picked does not: every entry already
fits, so the choice is between good options.

## Format

One list item per GIF. A URL, then a pipe, then tags.

```
- https://media.tenor.com/xxxxx/shrug.gif | shrug, dont care, whatever
- https://media.tenor.com/yyyyy/facepalm.gif | facepalm, disbelief, idiot
- https://media.tenor.com/zzzzz/slowclap.gif | slow clap, sarcastic, well done
```

Anything that is not a list item with a URL is ignored, so write notes freely.
The file is re-read on every use, so adding one needs no restart.

## Getting the links

Open the GIF in Discord, right-click, **Copy Link**. Anything Discord embeds
works - a direct `.gif`, or a Tenor or Giphy page URL.

## Tags are the whole thing

Tags are all the model sees; it never sees the URLs, so it picks on tags alone.

- **Tag the reaction, not the content.** `facepalm, disbelief` is useful.
  `man in blue shirt` is not - nobody reaches for a GIF because of the shirt.
- **Several tags each**, since the same GIF gets used for different feelings.
- **Untagged entries are skipped.** A GIF with no tags can never be chosen.

Thirty well-tagged GIFs beat three hundred untagged ones. Start with the ones
your group already overuses.
