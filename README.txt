ENCORE BLEED V2 PACK

This version adds:
- customizable welcome / goodbye / boost messages
- custom booster embed controls
- mod logs + delete/edit/join/leave/boost logs
- booster role sync
- auto member role
- jail / unjail
- lock / unlock
- slowmode
- sticky messages
- snipe
- info commands
- Last.fm commands
- saved warnings
- automod

FILES
- main.py
- utils.py
- keep_alive.py
- requirements.txt
- .replit
- data/settings.json
- data/warns.json
- data/automod.json
- data/lastfm_users.json
- data/sticky.json
- data/snipe.json

IMPORTANT SECRETS
Required:
- DISCORD_TOKEN

Optional for Last.fm:
- LASTFM_API_KEY

DISCORD DEVELOPER PORTAL
Turn on:
- SERVER MEMBERS INTENT
- MESSAGE CONTENT INTENT

SETUP COMMANDS
- /setmodlog
- /setdeletelog
- /seteditlog
- /setjoinlog
- /setboostlog
- /setwelcomechannel
- /togglewelcome
- /togglegoodbye
- /toggleboostmsg
- /setwelcomemsg
- /setgoodbyemsg
- /setboostmsg
- /setboosttitle
- /setboostfooter
- /setboostimage
- /setboostthumb
- /previewboost
- /previewmessages
- /setboosterrole
- /setmemberrole
- /setjailrole
- /boosterrefresh
- /automod
- /setcolor
- /config

TEMPLATE VARIABLES
You can use these in welcome / goodbye / boost messages:
- {mention}
- {user}
- {server}
- {member_count}

LAST.FM COMMANDS
- /setfm username
- /fm
- /fmtop

NOTES
- The bot role must be above the booster role and jail role.
- Sticky messages repost after every new message in that channel.
- Last.fm commands need a valid LASTFM_API_KEY in Replit Secrets.

BOOST EMBED EXTRAS
- /setboosttitle
- /setboostfooter
- /setboostimage
- /setboostthumb
- /previewboost


BOOSTER LAST.FM CUSTOM EMBEDS
- /toggleboosterfm
- /setboosterfmtitle
- /setboosterfmfooter
- /setboosterfmimage
- /setboosterfmthumb
- /previewboosterfm

How it works:
- boosters get the custom Last.fm embed only if /toggleboosterfm is enabled
- non-boosters keep the regular Last.fm bot-style embed
- the booster check uses the role set with /setboosterrole


BLEED-STYLE EXTRAS
- /sendembed
- /bleedtheme
- darker default embeds
- regular users keep a simpler /fm embed
- boosters can use the custom Last.fm embed system


POLISH PASS
- /fm now shows track scrobbles and total scrobbles when available
- /previewfm added
- /previewboosterfm now previews the polished booster Last.fm embed
- regular and booster Last.fm embeds were cleaned up
