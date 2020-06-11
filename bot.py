#!/usr/bin/env python3
import discord
import asyncio
import pygsheets
import datetime
import re
import time
import aiohttp
import async_timeout
import json
import io
import sys
import traceback
import sqlite3
import threading
import aiohttp_jinja2
import jinja2
import logging
import os
import random
import base64
import html
import pickle
import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from oauth2client.service_account import ServiceAccountCredentials
from aiohttp_session import setup, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from PIL import Image, ImageFont, ImageDraw
from subprocess import Popen, PIPE
from aiohttp import web

with open("secrets","r") as f:
    secrets = json.loads(f.read())

sentry_sdk.init(dsn=secrets["sentry thing"], integrations=[AioHttpIntegration()])

client = discord.Client()

gs = pygsheets.authorize(service_file="key.json")

ss = gs.open("Echo VR Feature Requests")
allS = ss.worksheet_by_title("All")
openS = ss.worksheet_by_title("Open")
rejS = ss.worksheet_by_title("Rejected")
doneS = ss.worksheet_by_title("Implemented")
planS = ss.worksheet_by_title("Planned")
stats = ss.worksheet_by_title("Stats")

pattern = re.compile(r"\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
pattern2 = re.compile(r"\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
newpattern = re.compile(r"\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Game [mM]ode[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
commentpattern = re.compile(r"^(\d{18})[^>].*?([^\s:-][\s\S]*)")
profilepattern = re.compile(r"esl.*\/(\d+)")

conn = sqlite3.connect("requests.db")
c = conn.cursor()

logger = logging.getLogger("logger")
logger.setLevel(logging.DEBUG)
f = logging.Formatter("%(asctime)s - %(funcName)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(f)
fh = logging.FileHandler("logs/%s.log"%str(datetime.datetime.now()))
fh.setLevel(logging.DEBUG)
fh.setFormatter(f)
logger.addHandler(ch)
logger.addHandler(fh)

encoder = json.JSONEncoder()

verifying = []

async def perm(reaction):
    global guild
    async for user in reaction.users():
        try:
            member = await guild.fetch_member(user.id)
            if discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or member == mateuszdrwal, member.roles) != None:
                return True
        except:
            pass
    return False

async def updateSheet():
    global c
    
    for sheet, criteria in [(openS, " WHERE status = 0 AND disabled = 0"),(planS, " WHERE status = 1 AND disabled = 0"),(rejS, " WHERE status = 2 AND disabled = 0"),(doneS, " WHERE status = 3 AND disabled = 0"),(allS, " WHERE disabled = 0")]:

        c.execute("SELECT * FROM requests"+criteria)
        entries = c.fetchall()
        
        newVals = []
        
        for entry in entries:
            if entry[8] == 0:
                status = "Open"
            if entry[8] == 1:
                status = "Planned"
            if entry[8] == 2:
                status = "Rejected"
            if entry[8] == 3:
                status = "Implemented"
            if entry[8] == 4:
                status = "Not applicable anymore"

            c.execute("SELECT * FROM responses WHERE mid = :mid", {"mid": entry[9]})
            responses = c.fetchall()

            newVals.append([datetime.datetime.fromtimestamp(entry[0]).strftime("%Y-%m-%d %H:%M:%S UTC"),
                            entry[1],
                            entry[3],
                            {"ea": "Echo Arena", "ec": "Echo Combat", "n/a":"Not Applicable"}.get(entry[14]),
                            entry[5],
                            entry[6]-entry[7],
                            entry[6],
                            entry[7],
                            status,
                            "\n\n".join(resp[2] for resp in responses),
                            entry[9],
                            entry[10]
                            ])
            
            await asyncio.sleep(0.01)
        
        newVals.sort(key=lambda r: int(r[6]))
        newVals.reverse()
        newVals.insert(0, ["Time Submitted","Member","Title","Mode","Description","Points","Upvotes","Downvotes","Status","Developer Response","Message ID","Member ID"])

        cells = []
        for i, row in enumerate(newVals):
            for j, val in enumerate(row):
                cells.append(pygsheets.Cell((i+1,j+1),str(val)))

        sheet.clear((len(newVals)+1,1))
        sheet.update_cells(cell_list=cells)

    cells = []
    cells.append(pygsheets.Cell("B8"))
    cells[-1].value = "Last updated at: %s"%datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    stats.update_cells(cell_list=cells)

class fakemember:
    pass

async def updateRequest(message):
    upvotes = 0
    downvotes = 0
    status = 0 #0: open, 1: in-progress, 2: rejected, 3: resolved, 4: Not applicable anymore
    cont = False

    c.execute("SELECT * FROM votes WHERE mid = :mid", {"mid": message.id})
    fetched = c.fetchall()
    uped = [vote[1] for vote in fetched if vote[2] and vote[4]]
    downed = [vote[1] for vote in fetched if vote[3] and vote[5]]
    c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": message.id})
    fetched = c.fetchall()
    
    webStatus = bool(fetched[0][13])
    lastStatus = fetched[0][8]

    if len(message.mentions) == 0:
        member = fakemember()
        member.id = fetched[0][10]
        member.name = "".join(fetched[0][1].split("#")[:-1])
        member.discriminator = int(fetched[0][1].split("#")[-1])
        message.mentions.append(member)
    
    for reaction in message.reactions:
        if reaction.emoji == "\u26d4":
            if await perm(reaction):
                c.execute("UPDATE requests SET disabled = 1 WHERE mid = :mid", {"mid": message.id})
                conn.commit()
                return
            
        elif reaction.emoji == "\U0001f5d3":
            if await perm(reaction) and status < 1 and not webStatus:
                status = 1
        elif reaction.emoji == "\u274c":
            if await perm(reaction) and status < 2 and not webStatus:
                status = 2
        elif reaction.emoji == "\u2705":
            if await perm(reaction) and status < 3 and not webStatus:
                status = 3

        elif reaction.emoji == "\U0001f44e":
            async for user in reaction.users():
                
                if user == client.user:
                    continue

                if reaction.message.author.bot:
                    if reaction.message.mentions[0].id == user.id:
                        continue
                else:
                    if reaction.message.author == user:
                        continue

                c.execute("SELECT * FROM votes WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                fetched = c.fetchall()
                if fetched != []:
                    if fetched[0][3] != 1 or fetched[0][5] != 1:
                        c.execute("UPDATE votes SET down = 1, downDiscord = 1 WHERE :mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                else:
                    c.execute("INSERT INTO votes VALUES (:mid, :uid, 0, 1, 0, 1)", {"mid": message.id, "uid": user.id})

                conn.commit()
                
                try:
                    downed.remove(user.id)
                except ValueError:
                    pass
            
        elif reaction.emoji in ["\U0001f44d","\U0001F60D","\u2764","\u261D","\U0001F446","\U0001F44C","\U0001F4AF",u"\N{WHITE HEAVY CHECK MARK}"]:
            async for user in reaction.users():

                if user == client.user:
                    continue
                
                if reaction.message.author.bot:
                    if reaction.message.mentions[0].id == user.id:
                        continue
                else:
                    if user in [reaction.message.author, client.user]:
                        continue

                c.execute("SELECT * FROM votes WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                fetched = c.fetchall()
                if fetched != []:
                    if fetched[0][2] != 1 or fetched[0][4] != 1:
                        c.execute("UPDATE votes SET up = 1, upDiscord = 1 WHERE :mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                else:
                    c.execute("INSERT INTO votes VALUES (:mid, :uid, 1, 0, 1, 0)", {"mid": message.id, "uid": user.id})

                conn.commit()
                
                try:
                    uped.remove(user.id)
                except ValueError:
                    pass

    for user in uped:
        c.execute("UPDATE votes SET up = 0, upDiscord = 0 WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user})
    for user in downed:
        c.execute("UPDATE votes SET down = 0, downDiscord = 0 WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user})
    conn.commit()

    c.execute("SELECT count(*) FROM votes WHERE up = 1 AND mid = :mid", {"mid": message.id})
    upvotes = c.fetchall()[0][0]
    c.execute("SELECT count(*) FROM votes WHERE down = 1 AND mid = :mid", {"mid": message.id})
    downvotes = c.fetchall()[0][0]

    devresp = []
    c.execute("SELECT * FROM responses WHERE mid = :mid", {"mid": message.id})
    for response in c.fetchall():
        devresp.append(str(jinja2.escape("%s:\n%s"%(response[3],response[2]))).replace("\n","<br/>"))
    devresp = "<br/><br/>".join(devresp)

    # c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": message.id})
    # fetched = c.fetchall()
    # text = {}
    # for name, index in [("title", 3), ("category", 4), ("description", 5), ("sugType", 2)]:
    #     text[name] = html.escape(html.unescape(fetched[0][index]))

    c.execute("UPDATE requests SET up = :up, down = :down, status = :status, devresp = :devresp WHERE mid = :mid", 
        {"mid": message.id,
        "up": upvotes,
        "down": downvotes,
        "status": status if not webStatus else lastStatus,
        "devresp": devresp,
        "author": "%s#%s"%(message.author.name, message.author.discriminator) if not message.author.bot else "%s#%s"%(message.mentions[0].name, message.mentions[0].discriminator)
        })
    
    conn.commit()

async def analyzeMessage(message, force=False, new=False):
    results = re.findall(pattern, message.clean_content)
    comment = re.findall(commentpattern, message.content)
    results2 = re.findall(pattern2, message.clean_content)
    newpatternResults = re.findall(newpattern, message.clean_content)
    if results == [] and results2 != []:
        results = [(results2[0][1], results2[0][0], results2[0][2], results2[0][3])]

    if comment != [] and message.author not in guild.members: return
    if comment != [] and discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or message.author == mateuszdrwal, message.author.roles) != None:
        comment = comment[0]
        id = int(comment[0])

        c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": id})

        if c.fetchall() != []:
            c.execute("SELECT * FROM responses WHERE rmid = :rmid", {"rmid":message.id})

            if c.fetchall() == []:
                c.execute("INSERT INTO responses VALUES (:mid, :rmid, :resp, :author)",{"mid": id, "rmid": message.id, "resp": comment[1], "author": message.author.name})
                conn.commit()
                await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")
            else:
                c.execute("UPDATE responses SET response = :resp WHERE mid = :mid AND rmid = :rmid",{"mid": id, "rmid": message.id, "resp": comment[1]})

            await updateRequest(await requestChannel.fetch_message(id))
        return
        
    if (force or (message.author == client.user and (results != [] or newpatternResults != []))) and message.id not in [466682006718251039]:
        await updateRequest(message)
        return

    if (results == [] and newpatternResults == []) or message.id == 403337281068466197:
        return
    
    c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": message.id})
    fetched = c.fetchall()
    if results != []:
        if fetched != []:
            c.execute("""UPDATE requests SET
            sugType = :sugType,
            title = :title,
            category = :category,
            description = :description,
            up = 0,
            down = 0
            WHERE mid = :mid""", {
                "sugType": html.escape(results[0][0]),
                "title": html.escape(results[0][1]),
                "category": html.escape(results[0][2]),
                "description": html.escape(results[0][3]),
                "mid": message.id
                })
        else:
            return

    else:

        if newpatternResults[0][1].lower() not in ["ea","ec","n/a"]:
            if new:
                await requestChannel.send(u"That mode is incorrect. please edit your message to make sure that the mode is either \"ea\" (for Echo Arena), \"ec\" (for Echo Combat) or \"n/a\" (for Not Applicable). You know it worked when i react with \U0001f44d and \U0001f44e")
            return

        if fetched != []:
            c.execute("""UPDATE requests SET
            title = :title,
            mode = :mode,
            description = :description,
            up = 0,
            down = 0
            WHERE mid = :mid""", {
                "title": html.escape(newpatternResults[0][0]),
                "mode": html.escape(newpatternResults[0][1].lower()),
                "description": html.escape(newpatternResults[0][2]),
                "mid": message.id
                })
        else:
            c.execute("""INSERT INTO requests VALUES (
            :time,
            :author,
            "",
            :title,
            "",
            :description,
            0,
            0,
            0,
            :mid,
            :uid,
            "",
            0,
            0,
            :mode
            )""", {
                "time": message.created_at.timestamp(),
                "author": html.escape("%s#%s"%(message.author.name, message.author.discriminator)),
                "title": html.escape(newpatternResults[0][0]),
                "mode": html.escape(newpatternResults[0][1].lower()),
                "description": html.escape(newpatternResults[0][2]),
                "mid": message.id,
                "uid": message.author.id
                })
            logger.info("new suggestion: %s"%newpatternResults[0][0])
            await message.add_reaction("\U0001F44D")
            await message.add_reaction("\U0001F44E")

    conn.commit()

    await updateRequest(message)

async def loop():
    global requestChannel, guild, conn, c
    await client.wait_until_ready()
    await asyncio.sleep(1)

    async for message in requestChannel.history(limit=None, oldest_first=False):
        await analyzeMessage(message)

    logger.info("initial update done")
    
    while True:

        c.execute("SELECT * FROM requests")
        for request in c.fetchall():
            try:
                message = await requestChannel.fetch_message(request[9])
            except discord.NotFound:
                c.execute("DELETE FROM requests WHERE mid = :mid", {"mid": request[9]})
                c.execute("DELETE FROM votes WHERE mid = :mid", {"mid": request[9]})
                c.execute("DELETE FROM responses WHERE mid = :mid", {"mid": request[9]})
                conn.commit()
                logger.info("removed request %s"%request[3])
                continue
            await analyzeMessage(message, True)

        try:
            await updateSheet()
            await asyncio.sleep(600)
        except Exception as error:
            logger.debug(error)
            gs = pygsheets.authorize(service_file="key.json")

            ss = gs.open("Echo VR Feature Requests")
            allS = ss.worksheet_by_title("All")
            openS  = ss.worksheet_by_title("Open")
            rejS  = ss.worksheet_by_title("Rejected")
            doneS  = ss.worksheet_by_title("Implemented")
            planS  = ss.worksheet_by_title("Planned")
            stats = ss.worksheet_by_title("Stats")

async def backup():
    while True:
        await asyncio.sleep(3600*12)
        logger.info("backing up db")
        Popen(["cp", "requests.db", "backups/backup-%s.db"%round(time.time())])

@client.event
async def on_reaction_add(reaction, user):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if reaction.message.channel == requestChannel: await analyzeMessage(reaction.message)

@client.event
async def on_reaction_remove(reaction, user):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if reaction.message.channel == requestChannel: await analyzeMessage(reaction.message)

@client.event
async def on_reaction_clear(message, reactions):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if message.channel == requestChannel: await analyzeMessage(message)

@client.event
async def on_message(message):

    if message.author == client.user: return

    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if message.channel == requestChannel: await analyzeMessage(message, new=True)

    if message.content == "!status":
        string = "Echo games servers status:\n"
        data = json.loads(await get("https://api.readyatdawn.com/status?projectid=rad14"))
        for service in data:
            if service["serviceid"] == "services": msg = service["message"]
            if service["serviceid"] in ["services","news"]: continue
            string += "%s %s: **%s**\n" % ((u"\N{WHITE HEAVY CHECK MARK}", service["serviceid"], "Online") if service["available"] else ("\u274c", service["serviceid"], "Offline"))
        string += "message: **%s**" % msg
        await message.channel.send(string)

    if message.content == "!verifyesl":
        if message.author.dm_channel == None: await message.author.create_dm()
        await message.author.dm_channel.send("Please send a link to your ESL profile here to continue verificaton")
        await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")

    id = re.findall(profilepattern, message.content)
    if len(id) > 0 and isinstance(message.channel, discord.DMChannel) and message.author.id not in verifying:
        verifying.append(message.author.id)
        id = id[0]
        if message.author.dm_channel == None: await message.author.create_dm()
        code = base64.b64encode(random.getrandbits(96).to_bytes(12, "big")).decode()
        await message.author.dm_channel.send("To finish verifying go to your profile (https://play.eslgaming.com/player/edit/%s/) and add the folowing text to your short description (not the long one!) temporarly: ```%s```Do this within the next 10 minutes. I will be checking for updates in the background and notify you when you are verified. If you have any issues, contact mateuszdrwal#9960."%(id, code))
        logger.info("%s verifying..."%message.author.display_name)

        try:
            async with async_timeout.timeout(600):
                while True:
                    data = await get("https://play.eslgaming.com/player/%s/"%id)
                    if code in data: break #not the most secure, but who cares. no idea why im forcing verification anyways
                    time.sleep(10)
        except asyncio.TimeoutError:
            if message.author.dm_channel == None: await message.author.create_dm()
            await message.author.dm_channel.send("The time has expired. If you want to verify again, please resend your profile link in this chat.")
            logger.info("failed verifying %s"%message.author.display_name)
            verifying.remove(message.author.id)
            return

        c.execute("DELETE FROM esl WHERE uid = :uid", {"uid": message.author.id})
        c.execute("INSERT INTO esl VALUES (:uid, :eid)", {"uid": message.author.id, "eid": id})
        conn.commit()
        if message.author.dm_channel == None: await message.author.create_dm()
        await message.author.dm_channel.send("Your ESL account has been successfully verified. You can now remove the text from your short description. If you ever want to unverify, do `!unverifyesl`")
        logger.info("verifying %s successful"%message.author.display_name)
        verifying.remove(message.author.id)

    if message.content == "!unverifyesl":
        c.execute("DELETE FROM esl WHERE uid = :uid", {"uid": message.author.id})
        await message.author.dm_channel.send("Your discord account is no longer linked to your ESL account.")

    #if message.content.startswith("!map"):
    #    with open("maps.pickle", "rb") as f:
    #        await message.channel.send(random.choice(pickle.load(f)))
    
    if message.content.startswith("!options") and (discord.utils.find(lambda r: r.name == "Event Managers", message.author.roles) or message.author.id == 140504440930041856):
        items = message.content.split()[1:]
        if items != []:
            with open("maps.pickle", "wb") as f:
                pickle.dump(items, f)
            await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")
            return
        await message.add_reaction(u"\N{CROSS MARK}")

regionalRoles = [328669711086780426, 328669659412955137]

roles = [{
    "role": 548653243216166942,
    "message": 548643103956008981,
    "emoji": "HeartEcho",
    "removeOnly": True,
    "removeBefore": []
}, {
    "role": 328669659412955137,
    "message": 548643103956008981,
    "emoji": "flag_us_ca",
    "removeOnly": False,
    "removeBefore": regionalRoles
}, {
    "role": 328669711086780426,
    "message": 548643103956008981,
    "emoji": "🇪🇺",
    "removeOnly": False,
    "removeBefore": regionalRoles
}
]

@client.event
async def on_raw_reaction_add(payload):
    for role in roles:
        if payload.message_id == role["message"] and payload.emoji.name == role["emoji"]:
            await (await (client.get_channel(payload.channel_id)).fetch_message(role["message"])).add_reaction(payload.emoji)
            member = await guild.fetch_member(payload.user_id)
            for toRemove in role["removeBefore"]:
                await member.remove_roles(guild.get_role(toRemove))
            if role["removeOnly"]:
                await member.remove_roles(guild.get_role(role["role"]))
            else:
                await member.add_roles(guild.get_role(role["role"]))

@client.event
async def on_raw_reaction_remove(payload):
    for role in roles:
        if payload.message_id == role["message"] and payload.emoji.name == role["emoji"]:
            member = await guild.fetch_member(payload.user_id)
            await member.remove_roles(guild.get_role(role["role"]))

@client.event
async def on_member_join(member):
    if member.guild == guild:
        #await member.add_roles(guild.get_role(548653243216166942))
        pass

@client.event
async def on_message_edit(before, message):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if message.channel == requestChannel: await analyzeMessage(message)

async def cupTask(cupChannel, filesuffix, link):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    await asyncio.sleep(5)

    cupChannel = client.get_channel(cupChannel)

    while True:

        #getting cups
        cups = []
        raw = await eslApi(link.format("inProgress,upcoming"))
        for cup in raw.values():
            cuptime = datetime.datetime.strptime(cup["timeline"]["inProgress"]["begin"].replace(":",""), "%Y-%m-%dT%H%M%S%z").timestamp()
            if ("registration" in cup["name"]["full"].lower() or "stage" in cup["name"]["full"].lower() or "qualifier" in cup["name"]["full"].lower() or "vrl" in cup["name"]["full"].lower() or cuptime-time.time() < 0) and not ("summer" in cup["name"]["full"].lower()):
                cups.append([cuptime, cup["id"], cup["name"]["full"]])
        
        if len(cups) == 0:
            logger.info("no cups for %s, sleeping one hour" % filesuffix)
            await asyncio.sleep(3600)
            continue
            
        cups.sort()
        cup = cups[0]

        waitTime = cup[0]-time.time()#testing
        if waitTime > 0:
            logger.info("waiting %s for %s" % (waitTime, cup[2]))
            await asyncio.sleep(waitTime) #waiting for cup

            #initial cup message
            raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

            teamList = []
            for team in raw:
                if team["status"] == "checkedIn":
                    players = await eslApi("/play/v1/teams/%s/members"%team["id"])
                    teamList.append([team["seed"], team["name"], ", ".join([player["user"]["nickname"] for player in players.values() if player["membership"]["role"] != "inactive"])])
            teamList.sort()
                            
            await cupChannel.send("The weekly cup has begun! Good luck to everyone participating!")
            await cupChannel.send("Here are the seeds participating today:\n\n%s"%"\n".join(["**%s. %s**\n    *%s*"%(i+1, name[1], name[2]) for i, name in enumerate(teamList)]))
            await cupChannel.send("If you want to get private messages everytime the next round starts/you have a new match to play, go to <#328962843800109067> and type `!verifyesl`")

        raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

        pixlim = 384

        allcups = [cup[1]]#testing


        while True: #cup loop
            cups2 = await eslApi(link.format("inProgress"))

            pairings = []
            for cup2 in cups2.values():
                if "cup" not in cup2["name"]["full"].lower():
                    continue
                if cup2["id"] not in allcups and "summer" not in cup2["name"]["full"].lower(): allcups.append(cup2["id"])

            for cup2 in allcups + [cup[1]]:
                pairings += await eslApi("/play/v1/leagues/%s/matches"%cup2)
            #pairings += await eslApi("/play/v1/matches") #testing

            if "error" in pairings:
                continue

            for pairing in pairings: #looping through every match in every cup
                c.execute("SELECT * FROM matches")
                ids = c.fetchall()
                c.execute("SELECT * FROM openmatches")
                oids = c.fetchall()

                ended = pairing["calculatedAt"]

                teams2 = [pairing["contestants"][0]["team"]["name"],pairing["contestants"][1]["team"]["name"]]
                points = [pairing["result"]["score"].get(pairing["contestants"][0]["team"]["id"]),pairing["result"]["score"].get(pairing["contestants"][1]["team"]["id"])]

                if (pairing["id"],) not in oids:# match notifications
                    teamids = [pairing["contestants"][0]["team"]["id"],pairing["contestants"][1]["team"]["id"]]
                    
                    for i, team in enumerate(teamids):

                        if team == None: continue
                        members = await eslApi("/play/v1/teams/%s/members"%team)

                        for member, eslmember in members.items():
                            if eslmember["membership"]["role"] == "inactive": continue
                            c.execute("SELECT * FROM esl WHERE eid = :eid", {"eid": member})
                            user = c.fetchall()
                            if len(user) == 0: continue
                            user = user[0]
                            member = await guild.fetch_member(user[0])
                            if member == None: continue
                            if member.dm_channel == None: await member.create_dm()

                            if (points[0] == None or points[1] == None) and ended == None: # if its a bye
                                if pairing["status"] == "closed":
                                    await member.dm_channel.send("Take a rest. You recieved a bye in the next round of the cup.")
                                    logger.debug("sent bye message")
                                    c.execute("INSERT INTO openmatches VALUES (:id)", {"id": pairing["id"]})
                                    conn.commit()
                                continue


                            if pairing["status"] == "open":
                                opponentmembers = await eslApi("/play/v1/teams/%s/members"%teamids[-1+i])
                                await member.dm_channel.send("Next round has started. Wild **%s** appeared!\nMembers: *%s*"%(teams2[-1+i], ", ".join([player["user"]["nickname"] for player in opponentmembers.values() if player["membership"]["role"] != "inactive"])))
                                logger.debug("sent round message")
                                c.execute("INSERT INTO openmatches VALUES (:id)", {"id": pairing["id"]})
                                conn.commit()


                if pairing["status"] != "closed" or (pairing["id"],) in ids:
                    continue

                if points[0] == None or points[1] == None or ended == None:

                    c.execute("INSERT INTO matches VALUES (:id)", {"id": pairing["id"]})
                    conn.commit()
                    continue

                #draw image
                logo1 = Image.open(io.BytesIO(await requestImage(pairing["contestants"][0]["team"]["logo"])))
                logo2 = Image.open(io.BytesIO(await requestImage(pairing["contestants"][1]["team"]["logo"])))
                midtext = "VS"
                logospacing = 20
                textspacing = 20
                font = ImageFont.truetype("font.ttf", 50)
                bold = ImageFont.truetype("bold.ttf", 50)
                max = font.getsize("Tq")[1]
                y = 90-int(max/2)
                color = (128,128,128,255)

                team1font = font
                team2font = font

                if points[0] > points[1]:
                    team1font = bold
                elif points[0] < points[1]:
                    team2font = bold

                team1size = team1font.getsize(teams2[0])[0]
                team2size = team2font.getsize(teams2[1])[0]

                while team1size > pixlim:
                    teams2[0] = teams2[0][0:len(teams2[0])-1]
                    team1size = team1font.getsize(teams2[0])[0]
                    
                while team2size > pixlim:
                    teams2[1] = teams2[1][0:len(teams2[1])-1]
                    team2size = team2font.getsize(teams2[1])[0]
                
                midsize = font.getsize(midtext)[0]

                size = pixlim
                team1extra = (pixlim - team1size)/2
                team2extra = (pixlim - team2size)/2

                length = 180*2+logospacing*2 + textspacing*2 + size*2 + midsize
                img = Image.new("RGBA",(length, 180), color=(255,255,255,0))
                draw = ImageDraw.Draw(img)
                img.paste(logo1, (0,0))
                img.paste(logo2, (length-180,0))
                draw.text((180+logospacing+team1extra, y), teams2[0], font=team1font, fill=color)
                draw.text((180+logospacing+size+textspacing, y), midtext, font=font, fill=color)
                draw.text((180+logospacing+size+midsize+textspacing*2+team2extra, y), teams2[1], font=team2font, fill=color)

                draw.text((180+logospacing+size-font.getsize(str(points[0]))[0],y+5+max), str(points[0]), font=team1font, fill=color)
                draw.text((180+logospacing+size+textspacing*2+midsize,y+5+max), str(points[1]), font=team2font, fill=color)

                img.save("match.png")

                while True:
                    try:
                        #await cupChannel.send(file=discord.File("match.png"))
                        break
                    except ValueError:
                        os.remove("match.png")
                        img.save("match.png")

                c.execute("INSERT INTO matches VALUES (:id)", {"id": pairing["id"]})
                conn.commit()

            c.execute("SELECT * FROM matches")
            ids = c.fetchall()

            for pairing in pairings:
                if (pairing["id"],) not in ids:
                    break
            else:
                inProgressCups = await eslApi(link.format("inProgress"))
                a = True
                for cup2 in allcups:
                    if str(cup2) in inProgressCups:
                        a = False
                if time.time() - cup[0] > 3600 and a:
                    break

        await cupChannel.send("The cup has now ended! Good job everyone!")

        results = []
        for cup2 in allcups:
            ranking = await eslApi("/play/v1/leagues/%s/ranking"%cup2)
            if ranking["ranking"] == None:
                continue
            teams2 = []
            for team in ranking["ranking"]:
                players = await eslApi("/play/v1/teams/%s/members"%team["team"]["id"])
                teams2.append([team["position"], team["team"]["name"], ", ".join([player["user"]["nickname"] for player in players.values() if player["membership"]["role"] != "inactive"])])
            teams2.sort()
            results.append("%s"%"\n".join(["**%s. %s**\n    *%s*"%(team[0],team[1],team[2]) for team in teams2]))

        await cupChannel.send("Here are the final rankings of today's cup:\n\n%s"%"\n\n\n".join(results))

        logger.info("cup done")
        await asyncio.sleep(3600*12)

async def eslApi(path):
    while True:
        try:
            if False and ("matches" in path or "leagues?" in path): #testing
                raw = await get("https://eslmock.mateuszdrwal.com"+path)
            else:
                raw = await get("https://api.eslgaming.com"+path)

            return json.loads(raw)
        except json.JSONDecodeError:
            pass

async def get(url, headers=None):
    global http
    while True:
        try:
            with async_timeout.timeout(30):
                async with http.get(url, headers=headers) as response:
                    return await response.text()
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            raise e

async def post(url, data=None, headers=None):
    global http
    while True:
        try:
            with async_timeout.timeout(30):
                async with http.post(url, data=data, headers=headers) as response:
                    return await response.json()
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            raise e

async def requestImage(url):
    global http
    while True:
        try:
            with async_timeout.timeout(30):
                async with http.get(url) as response:
                        return await response.read()
                    
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            raise e

@client.event
async def on_ready():
    global requestChannel, guild, errorChannel, mateuszdrwal

    await client.wait_until_ready()
    
    logger.debug(client.user.name)
    logger.debug(client.user.id)

    requestChannel = await client.fetch_channel(403335187062194188)
    # errorChannel = await client.fetch_channel(424701844942618634)
    mateuszdrwal = await client.fetch_user(140504440930041856)
    guild = await client.fetch_guild(326412222119149578)

    await client.change_presence(activity=discord.Activity(name='Echo Combat',type=discord.ActivityType.streaming))

    logger.info("discord.py initialized")

# async def errorCatcher(task):
#     global errorChannel, mateuszdrwal
#     try:
#         await task
#     except Exception as e:
#         err = sys.exc_info()
#         await errorChannel.send("%s\n```%s\n\n%s```"%(mateuszdrwal.mention,"".join(traceback.format_tb(err[2])),err[1].args[0]))

@client.event
async def on_error(event, *args, **kwargs):
    await client.wait_until_ready()
    await asyncio.sleep(1)
    err = sys.exc_info()
    sentry_sdk.capture_exception()
    # await errorChannel.send("%s\n```%s\n\n%s```"%(mateuszdrwal.mention,"".join(traceback.format_tb(err[2])),err[1].args[0]))
    logger.warn("".join(traceback.format_tb(err[2])),err[1].args[0])

async def startup():
    global http, conn, c
    http = aiohttp.ClientSession()

    conn = sqlite3.connect("requests.db")
    c = conn.cursor()


client.loop.create_task(startup())
client.loop.create_task(loop())
client.loop.create_task(backup())
# client.loop.create_task(cupTask(419202299991425024,"EU_ea","/play/v1/leagues?&states={}&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrlechoarena-eu-portal&includeHidden=0"))
# client.loop.create_task(cupTask(419202299991425024,"NA_ea","/play/v1/leagues?states={}&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrlechoarena-na-portal&includeHidden=0"))
# client.loop.create_task(cupTask(419202299991425024,"EU_ec","/play/v1/leagues?&states={}&path=%2Fplay%2Fechocombat%2F&portals=&tags=vrlechocombat-eu-portal&includeHidden=0"))
# client.loop.create_task(cupTask(419202299991425024,"NA_ec","/play/v1/leagues?states={}&path=%2Fplay%2Fechocombat%2F&portals=&tags=vrlechocombat-na-portal&includeHidden=0"))
#client.loop.create_task(errorCatcher(cupTask(377230334288330753,"EU","/play/v1/leagues?&states={}&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrlechoarena-eu-portal&includeHidden=0")))
#client.loop.create_task(errorCatcher(cupTask(350354518502014976,"NA","/play/v1/leagues?states={}&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrlechoarena-na&includeHidden=0")))
#client.loop.create_task(errorCatcher(cupTask(390482469469552643,"TEST","/play/v1/leagues?states={}"))) #testing
client.loop.create_task(client.start(secrets["discord token"]))





routes = web.RouteTableDef()
app = web.Application(loop=client.loop)
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('./templates'))

def ip(request):
    return request.headers["X-Real-IP"]

def who(session, request):
    return "%s (%s)"%(session["username"], ip(request)) if "username" in session else ip(request)

@routes.get("/")
@aiohttp_jinja2.template("home.html")
async def home(request):
    session = await get_session(request)

    desc = "The feature requests website for the VR multiplayer game Echo VR. Submit your own feature requests here!"
    author = ""
    title = "Echo VR Feature Requests"

    if request.query.get("request","null") != "null":
        return web.HTTPPermanentRedirect("/request/%s"%request.query.get("request","null"))

    if "username" not in session and request.query.get("r", None) != None and "Discordbot" not in request.headers.get("user-agent"): return web.HTTPFound("https://discordapp.com/api/oauth2/authorize?client_id=427817724966600705&redirect_uri=https%3A%2F%2Fearequests.mateuszdrwal.com%2Fauth%3Fr%3D1&response_type=code&scope=identify")

    return {"error": request.query.get("error", None), "success": request.query.get("success", None), "desc": desc, "author": author, "title": title, "submit": request.query.get("r", None), **session}

@routes.get("/request/{requestid}")
@aiohttp_jinja2.template("home.html")
async def request(request):
    session = await get_session(request)

    c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": request.match_info.get("requestid")})
    fetched = c.fetchall()
    if len(fetched) != 0:
        desc = fetched[0][5]
        author = fetched[0][1]
        title = fetched[0][3] + " | Echo VR Feature Request"

    if "username" not in session and request.query.get("r", None) != None and "Discordbot" not in request.headers.get("user-agent"): return web.HTTPFound("https://discordapp.com/api/oauth2/authorize?client_id=427817724966600705&redirect_uri=https%3A%2F%2Fearequests.mateuszdrwal.com%2Fauth%3Fr%3D1&response_type=code&scope=identify")

    return {"error": None, "success": None, "desc": desc, "author": author, "title": title, "submit": None, **session}


@routes.get("/api/requests")
async def rawrequests(request):
    session = await get_session(request)

    if request.query.get("request","null") == "null":
        c.execute("SELECT * FROM requests WHERE disabled = 0")
    else:
        c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": request.query["request"]})

    fetched = c.fetchall()

    requests = {request[9]: {"date": datetime.date.fromtimestamp(request[0]).isoformat(),
                             "time": datetime.datetime.fromtimestamp(request[0]).isoformat(),
                             "author": request[1],
                             "sugtype": request[2],
                             "title": request[3],
                             "category": request[4],
                             "description": request[5],
                             "up": request[6],
                             "down": request[7],
                             "status": ["Open","Planned","Rejected","Implemented","Not applicable anymore"][request[8]],
                             "statusCode": request[8],
                             "mid": str(request[9]),
                             "vote": {"up": 0, "down": 0, "upDiscord": 0, "downDiscord": 0},
                             "devresp": request[11],
                             "self": int(request[10]) == int(session.get("id",0)),
                             "timestamp": request[0],
                             "mode": request[14]
                             } for request in fetched}

    if "username" in session:
        c.execute("SELECT * FROM votes WHERE uid = :uid", {"uid": session["id"]})
        fetched = c.fetchall()
        for vote in fetched:
            if vote[0] not in requests: continue
            requests[vote[0]]["vote"]["up"] = vote[2]
            requests[vote[0]]["vote"]["down"] = vote[3]
            requests[vote[0]]["vote"]["upDiscord"] = vote[4]
            requests[vote[0]]["vote"]["downDiscord"] = vote[5]

    return web.Response(text=encoder.encode(requests))

@routes.get("/login")
async def login(request):
    return web.HTTPFound("https://discordapp.com/api/oauth2/authorize?client_id=427817724966600705&redirect_uri=https%3A%2F%2Fearequests.mateuszdrwal.com%2Fauth&response_type=code&scope=identify")

@routes.get("/auth")
async def auth(request):
    try:
        if "code" not in request.query:
            return web.HTTPFound("/")

        redirect = "https://earequests.mateuszdrwal.com/auth"
        if request.query.get("r") != None: redirect += "?r=1"

        data = {
            'client_id': secrets["client id"],
            'client_secret': secrets["client secret"],
            'grant_type': 'authorization_code',
            'code': request.query["code"],
            'redirect_uri': redirect
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        response = await post("https://discordapp.com/api/oauth2/token", data, headers)
        session = await get_session(request)
        assert "access_token" in response
        response = json.loads(await get("https://discordapp.com/api/users/@me", {"Authorization": "Bearer %s"%response["access_token"]}))
        assert "username" in response
        session["username"] = response["username"]
        session["id"] = response["id"]
        session["avatar"] = "https://cdn.discordapp.com/avatars/%s/%s.png?size=32"%(response["id"], response["avatar"])

        member = await guild.fetch_member(int(response["id"]))
        if member != None and discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or member == mateuszdrwal or member.id == 197276995787161600, member.roles) != None:
            session["admin"] = True
            logger.info("admin %s logged in"%response["username"])
        else:
            session["admin"] = False
            logger.info("%s logged in"%response["username"])
        return web.HTTPFound("/") if request.query.get("r") == None else web.HTTPFound("/?r=1")
    except AssertionError:
        logger.warn("error when logging in %s. queries: %s discord api response: %s"%(who(session, request), request.query, response))
        return web.HTTPFound("/?error=An+error+has+occurred+while+trying+to+log+in.+Please+try+again.+If+the+issue+persists+please+PM+me%2C+mateuszdrwal%239960")

@routes.get("/logout")
async def logout(request):
    session = await get_session(request)
    if "username" in session:
        logger.info("%s logging out"%session["username"])
    else:
        logger.warn("%s logging out without being logged in"%who(session, request))
    session.invalidate()
    return web.HTTPFound("/")

@routes.get("/spreadsheet")
async def spreadsheet(request):
    return web.HTTPFound("https://docs.google.com/spreadsheets/d/1l32dkgQSoyVSAJZ8ENMjy_dXC4JIpLTu37sQ9QbcPSY/edit#gid=2040872354")

@routes.post("/api/vote")
async def vote(request):
    try:
        session = await get_session(request)
        if session.get("username") == None: return web.HTTPFound("/login") #redirect if not logged in
        assert "id" in request.query and "target" in request.query and "up" in request.query #all queries are present
        assert (18 <= len(request.query["id"]) <= 19) and request.query["target"] in ["0","1"] and request.query["up"] in ["0","1"] #query data is valid
        c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": request.query["id"]})
        fetched = c.fetchall()
        assert fetched != [] #request exists
        assert int(fetched[0][10]) != int(session["id"]) #not voting on yourself
        c.execute("SELECT * FROM votes WHERE mid = :mid AND uid = :uid", {"mid": request.query["id"], "uid": session["id"]})
        fetched = c.fetchall()
        if fetched != []:
            if int(request.query["up"]):
                assert not fetched[0][4]#not voted on discord
            else:
                assert not fetched[0][5]#not voted on discord

        if fetched == []:
            if int(request.query["up"]):
                c.execute("INSERT INTO votes VALUES (:mid, :uid, :target, 0, 0, 0)", {"target": int(request.query["target"]), "mid": request.query["id"], "uid": session["id"]})
            else:
                c.execute("INSERT INTO votes VALUES (:mid, :uid, 0, :target, 0, 0)", {"target": int(request.query["target"]), "mid": request.query["id"], "uid": session["id"]})
        else:
            if int(request.query["up"]):
                c.execute("UPDATE votes SET up = :target WHERE mid = :mid AND uid = :uid", {"target": int(request.query["target"]), "mid": request.query["id"], "uid": session["id"]})
            else:
                c.execute("UPDATE votes SET down = :target WHERE mid = :mid AND uid = :uid", {"target": int(request.query["target"]), "mid": request.query["id"], "uid": session["id"]})
        conn.commit()
        await updateRequest(await requestChannel.fetch_message(request.query["id"]))
        logger.info("%s %svoted %s setting %svote"%(session["username"], "" if int(request.query["target"]) else "un", request.query["id"], "up" if int(request.query["up"]) else "down"))
        return web.Response(text="OK")
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

@routes.post("/api/newrequest")
async def newrequest(request):
    data = await request.post()
    session = await get_session(request)
    try:
        assert "title" in data and "mode" in data and "description" in data
        assert len(data["title"]) <= 100 and len(data["description"]) <= 1700
        assert data["mode"] in ["ea","ec","n/a"]
        assert "username" in session
    except AssertionError:
        logger.warning("%s is being suspicious with data:"%who(session, request))
        logger.debug(data)
        logger.debug(session)
        return web.HTTPBadRequest()

    try:
        assert client.get_user(int(session["id"])) != None
    except AssertionError:
        logger.info("%s tried making a request without being in the discord"%who(session, request))
        return web.HTTPFound("/?error=You%20are%20trying%20to%20create%20a%20request%20with%20a%20discord%20account%20that%20is%20not%20in%20the%20Echo%20Games%20discord.%20Please%20make%20sure%20you%20are%20logged%20on%20to%20the%20correct%20discord%20account%20or%20join%20the%20Echo%20Games%20discord.")

    
    user = client.get_user(int(session["id"]))
    message = await requestChannel.send("New request submitted from website by %s:\n\n**Title**: %s\n**Game mode**: %s\n**Description**: %s"%(user.mention, data["title"], {"ea":"Echo Arena", "ec": "Echo Combat", "n/a": "Not Applicable"}.get(data["mode"]), data["description"]))
    c.execute("INSERT INTO requests VALUES (:created, :author, '', :title, '', :description, 0, 0, 0, :mid, :uid, '', 0, 0, :mode)", {"created": time.time(), "author": "%s#%s"%(user.name, user.discriminator), "title": html.escape(data["title"]), "mode": html.escape(data["mode"]), "description": html.escape(data["description"]), "mid": message.id, "uid": user.id})
    conn.commit()
    await message.add_reaction("\U0001F44D")
    await message.add_reaction("\U0001F44E")
    await analyzeMessage(message)
    logger.info("%s created a request titled \"%s\""%(session["username"], data["title"]))
    return web.HTTPFound("/?success=Request%20created%21")

@routes.post("/api/devresp")
async def devresp(request):
    data = await request.post()
    session = await get_session(request)
    try:
        assert "id" in data and "devresp" in data
        assert len(data["id"]) == 18
        assert "username" in session
        assert session["admin"]
        assert data["devresp"] != ""
        int(data["id"])
        c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": data["id"]})
        assert c.fetchall() != []
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious with data:"%who(session, request))
        logger.debug(data)
        return web.HTTPBadRequest()

    c.execute("INSERT INTO responses VALUES (:mid, 0, :resp, :author)", {"mid": data["id"], "resp": data["devresp"], "author": session["username"]})
    conn.commit()
    await updateRequest(await requestChannel.fetch_message(data["id"]))
    logger.info("%s responded to %s"%(session["username"], data["id"]))
    return web.Response(text="OK")

@routes.post("/api/remove")
async def remove(request):
    session = await get_session(request)
    try:
        assert "id" in request.query
        assert (18 <= len(request.query["id"]) <= 19)
        int(request.query["id"])
        assert "username" in session
        assert session["admin"]
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("UPDATE requests SET disabled = 1 WHERE mid = :mid", {"mid": request.query["id"]})
    conn.commit()
    logger.info("%s removed %s"%(session["username"], request.query["id"]))
    return web.Response(text="OK")

@routes.post("/api/status")
async def status(request):
    session = await get_session(request)
    try:
        assert "id" in request.query and "target" in request.query
        assert (18 <= len(request.query["id"]) <= 19)
        int(request.query["id"])
        assert "username" in session
        assert session["admin"]
        int(request.query["target"])
        assert 0 <= int(request.query["target"]) < 5
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("UPDATE requests SET status = :status, webStatus = :webStatus WHERE mid = :mid", {"status": request.query["target"], "webStatus": 1 if int(request.query["target"]) != 0 else 0,"mid": request.query["id"]})
    conn.commit()
    logger.info("%s updated status of %s to %s"%(session["username"], request.query["id"], ["Open","Planned","Rejected","Implemented","Not applicable anymore"][int(request.query["target"])]))
    return web.Response(text="OK")

@routes.post("/api/mode")
async def mode(request):
    session = await get_session(request)
    try:
        assert "id" in request.query and "target" in request.query
        assert (18 <= len(request.query["id"]) <= 19)
        int(request.query["id"])
        assert "username" in session
        assert session["admin"]
        assert request.query["target"] in ["ea","ec","n/a"]
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("UPDATE requests SET mode = :mode WHERE mid = :mid", {"mode": request.query["target"], "mid": request.query["id"]})
    conn.commit()
    logger.info("%s updated mode of %s to %s"%(session["username"], request.query["id"], request.query["target"]))
    return web.Response(text="OK")

@routes.post("/api/merge")
async def merge(request):
    data = await request.post()
    session = await get_session(request)
    try:
        assert "id" in data and "id_from" in data
        assert (18 <= len(data["id"]) <= 19)
        assert (18 <= len(data["id_from"]) <= 19)
        int(data["id"])
        int(data["id_from"])
        assert int(data["id"]) != int(data["id_from"])
        assert "username" in session
        assert session["admin"]
    except (ValueError, AssertionError):
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    logger.info("backing up before merge...")
    Popen(["cp", "requests.db", "backups/backup-%s-BEFORE-MERGE.db"%round(time.time())])
    await asyncio.sleep(2) # quick and dirty, cant be bothered to wait for the backup properly

    c.execute("SELECT * FROM votes WHERE mid = :mid", {"mid": data["id"]})
    fetched = c.fetchall()
    current_votes = {i[1]: {"up": i[2], "down": i[3], "upDiscord": i[4], "downDiscord": i[5]} for i in fetched}

    c.execute("SELECT * FROM votes WHERE mid = :mid", {"mid": data["id_from"]})
    fetched = c.fetchall()

    for old_vote in fetched:
        if old_vote[1] in current_votes:
            c.execute("UPDATE votes SET up = :up, down = :down, upDiscord = :upDiscord, downDiscord = :downDiscord WHERE mid = :mid AND uid = :uid", {"up": int(current_votes[old_vote[1]]["up"] or old_vote[2]), "down": int(current_votes[old_vote[1]]["down"] or old_vote[3]), "upDiscord": int(current_votes[old_vote[1]]["up"] and current_votes[old_vote[1]]["upDiscord"]), "downDiscord": int(current_votes[old_vote[1]]["down"] and current_votes[old_vote[1]]["downDiscord"]), "mid": data["id"], "uid": old_vote[1]})
        else:
            c.execute("INSERT INTO votes VALUES (:mid, :uid, :up, :down, 0, 0)", {"up": old_vote[2], "down": old_vote[3], "mid": data["id"], "uid": old_vote[1]})

    c.execute("UPDATE requests SET disabled = 1 WHERE mid = :mid", {"mid": data["id_from"]})
    conn.commit()

    await updateRequest(await requestChannel.fetch_message(data["id"]))

    logger.info("%s merged %s into %s"%(session["username"], data["id_from"], data["id"]))
    return web.Response(text="OK")

@routes.get("/robots.txt")
async def robots(request):
    return web.Response(text="""
User-agent: *
Disallow: /api/
Disallow: /login
Disallow: /logout
Disallow: /auth

Allow: /api/requests
Sitemap: https://earequests.mateuszdrwal.com/sitemap.txt
""")

@routes.get("/sitemap.txt")
async def siteamp(request):

    c.execute("SELECT * FROM requests WHERE disabled = 0")
    fetched = c.fetchall()

    string = "\n".join("https://earequests.mateuszdrwal.com/request/%s"%request[9] for request in fetched)

    return web.Response(text=string)

app.router.add_static("/static","static")
setup(app, EncryptedCookieStorage(open("cookiekey", "rb").readline()))
app.add_routes(routes)
web.run_app(app,port=50001)
