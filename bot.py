#!/usr/bin/env python3
import discord, asyncio, pygsheets, datetime, re, time, aiohttp, async_timeout, json, io, sys, traceback, sqlite3, threading, aiohttp_jinja2, jinja2, logging
from oauth2client.service_account import ServiceAccountCredentials
from aiohttp_session import setup, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from PIL import Image, ImageFont, ImageDraw
from subprocess import Popen, PIPE
from aiohttp import web

client = discord.Client()

with open("secrets","r") as f:
    secrets = json.loads(f.read())

gs = pygsheets.authorize(service_file="key.json")

ss = gs.open("Echo Arena Feature Requests")
allS = ss.worksheet_by_title("All")
openS  = ss.worksheet_by_title("Open")
rejS  = ss.worksheet_by_title("Rejected")
doneS  = ss.worksheet_by_title("Implemented")
planS  = ss.worksheet_by_title("Planned")
stats = ss.worksheet_by_title("Stats")

pattern = re.compile(r"\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
commentpattern = re.compile("(\d{18})[^>].*?([^\s:-][\s\S]*)")

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

async def perm(reaction):
    global guild
    async for user in reaction.users():
        try:
            member = guild.get_member(user.id)
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
                            entry[2],
                            entry[3],
                            entry[4],
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
        newVals.insert(0, ["Time Submitted","Member","Suggestion Type","Title","Category","Description","Points","Upvotes","Downvotes","Status","Developer Response","Message ID","Member ID"])

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
    try:
        webStatus = bool(fetched[0][13])
        lastStatus = fetched[0][8]
    except Exception as e:
        logger.debug(message)
        raise e
    
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

                if reaction.message.author.bot:
                    if reaction.message.mentions[0] == user:
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
            
        elif reaction.emoji in ["\U0001f44d","\U0001F60D","\u2764","\u261D","\U0001F446","\U0001F44C","\U0001F4AF"]:
            async for user in reaction.users():
                if reaction.message.author.bot:
                    if reaction.message.mentions[0] == user:
                        continue
                else:
                    if reaction.message.author == user:
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

    c.execute("UPDATE requests SET up = :up, down = :down, status = :status, devresp = :devresp WHERE mid = :mid", {"mid": message.id, "up": upvotes, "down": downvotes, "status": status if not webStatus else lastStatus, "devresp": devresp, "author": "%s#%s"%(message.author.name, message.author.discriminator) if not message.author.bot else "%s#%s"%(message.mentions[0].name, message.mentions[0].discriminator)})
    
    conn.commit()

async def analyzeMessage(message, force=False):
    results = re.findall(pattern, message.clean_content)
    comment = re.findall(commentpattern, message.content)
    
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

            await updateRequest(await requestChannel.get_message(id))
        return
        
    if results == [] or message.id == 403337281068466197:
        if force:
            await updateRequest(message)
        return
    

    c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": message.id})
    fetched = c.fetchall()
    if fetched != []:
        c.execute("""UPDATE requests SET
        sugType = :sugType,
        title = :title,
        category = :category,
        description = :description,
        up = 0,
        down = 0
        WHERE mid = :mid""", {
            "sugType": results[0][0],
            "title": results[0][1],
            "category": results[0][2],
            "description": results[0][3],
            "mid": message.id
            })
    else:
        c.execute("""INSERT INTO requests VALUES (
        :time,
        :author,
        :sugType,
        :title,
        :category,
        :description,
        0,
        0,
        0,
        :mid,
        :uid,
        "",
        0,
        0
        )""", {
            "time": message.created_at.timestamp(),
            "author": "%s#%s"%(message.author.name, message.author.discriminator),
            "sugType": results[0][0],
            "title": results[0][1],
            "category": results[0][2],
            "description": results[0][3],
            "mid": message.id,
            "uid": message.author.id
            })
        logger.info("new suggestion: %s"%results[0][1])

    conn.commit()

    await updateRequest(message)

async def loop():
    global requestChannel, guild, conn, c
    await client.wait_until_ready()
    await asyncio.sleep(1)

    async for message in requestChannel.history(limit=None, reverse=True):
        await analyzeMessage(message)

    logger.info("initial update done")
    
    while True:
        try:

            c.execute("SELECT * FROM requests")
            for request in c.fetchall():
                try:
                    message = await requestChannel.get_message(request[9])
                except discord.NotFound:
                    continue
                await analyzeMessage(message, True)

            await updateSheet()
            await asyncio.sleep(600)

        except Exception as error:
            logger.debug(error)
            gs = pygsheets.authorize(service_file="key.json")

            ss = gs.open("Echo Arena Feature Requests")
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
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if message.channel == requestChannel: await analyzeMessage(message)

@client.event
async def on_message_edit(before, message):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    if message.channel == requestChannel: await analyzeMessage(message)

async def cupTask(cupChannel, textInCup, link):
    if not client.is_ready():
        await client.wait_until_ready()
        await asyncio.sleep(5)
    await asyncio.sleep(5)

    cupChannel = client.get_channel(cupChannel)

    while True:

        cups = []
        raw = await eslApi(link.format("inProgress,upcoming"))
        for cup in raw.values():
            if textInCup not in cup["name"]["full"].lower():
                continue
            cups.append([datetime.datetime.strptime(cup["timeline"]["inProgress"]["begin"].replace(":",""), "%Y-%m-%dT%H%M%S%z").timestamp(),
                         cup["id"]
                         ])
        
        if len(cups) == 0:
            await asyncio.sleep(3600)
            continue
            
        cups.sort()
        cup = cups[0]

        waitTime = cup[0]-time.time()
        if waitTime > 0:
            logger.info("waiting %s"%waitTime)
            await asyncio.sleep(waitTime)

            raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

            teamList = []
            for team in raw:
                if team["status"] == "checkedIn":
                    players = await eslApi("/play/v1/teams/%s/members"%team["id"])
                    teamList.append([team["seed"], team["name"], ", ".join([player["user"]["nickname"] for player in players.values() if player["membership"]["role"] != "inactive"])])
            teamList.sort()
                            
            await cupChannel.send("The weekly cup has begun! Good luck to everyone participating!")
            await cupChannel.send("Here are the seeds participating today:\n\n%s"%"\n".join(["**%s. %s**\n    *%s*"%(i+1, name[1], name[2]) for i, name in enumerate(teamList)]))

        raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

        pixlim = 384

        try:
            open("tempFile"+textInCup, "r").close()
        except FileNotFoundError:
            open("tempFile"+textInCup,"w").close()

        allcups = [cup[1]]

        while True:
            await asyncio.sleep(60)
            cups2 = await eslApi(link.format("inProgress"))

            pairings = []
            for cup2 in cups2.values():
                if textInCup not in cup2["name"]["full"].lower():
                    continue
                if cup2["id"] not in allcups: allcups.append(cup2["id"])

            for cup2 in allcups + [cup[1]]:
                pairings += await eslApi("/play/v1/leagues/%s/matches"%cup2)

            for pairing in pairings:
                f = open("tempFile"+textInCup,"r")
                ids = f.readlines()
                f.close()

                ended = pairing["calculatedAt"]
                teams2 = [pairing["contestants"][0]["team"]["name"],pairing["contestants"][1]["team"]["name"]]
                points = [pairing["result"]["score"].get(pairing["contestants"][0]["team"]["id"]),pairing["result"]["score"].get(pairing["contestants"][1]["team"]["id"])]

                if pairing["status"] != "closed" or str(pairing["id"])+"\n" in ids:
                    continue

                if points[0] == None or points[1] == None or ended == None:
                    f = open("tempFile"+textInCup,"a")
                    f.write(str(pairing["id"])+"\n")
                    f.close()
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
                        await cupChannel.send(file=discord.File("match.png"))
                        break
                    except ValueError:
                        os.remove("match.png")
                        img.save("match.png")

                f = open("tempFile"+textInCup,"a")
                f.write(str(pairing["id"])+"\n")
                f.close()

            f = open("tempFile"+textInCup,"r")
            ids = f.readlines()
            f.close()
            for pairing in pairings:
                if str(pairing["id"])+"\n" not in ids:
                    break
            else:
                if time.time() - cup[0] > 7200 and await eslApi("/play/v1/leagues?types=&states=inProgress&skill_levels=&limit.total=8&path=%2Fplay%2Fechoarena%2Feurope%2F&portals=&tags=vrclechoarena-eu-portal&includeHidden=0") == {}:
                    break

        Popen(["rm","tempFile"+textInCup])
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
    raw = await get("https://api.eslgaming.com"+path)
    return json.loads(raw)

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
    
    logger.debug(client.user.name)
    logger.debug(client.user.id)

    requestChannel = client.get_channel(403335187062194188)
    matpmChannel = client.get_channel(412554371923050496)
    errorChannel = client.get_channel(424701844942618634)

    mateuszdrwal = client.get_user(140504440930041856)
    guild = client.get_guild(326412222119149578)

    await client.change_presence(activity=discord.Activity(name='Echo Combat',type=discord.ActivityType.streaming))

    logger.info("discord.py initialized")

async def errorCatcher(task):
    global errorChannel, mateuszdrwal
    try:
        await task
    except Exception as e:
        err = sys.exc_info()
        await errorChannel.send("%s\n```%s\n\n%s```"%(mateuszdrwal.mention,"".join(traceback.format_tb(err[2])),err[1].args[0]))

@client.event
async def on_error(event, *args, **kwargs):
    await client.wait_until_ready()
    await asyncio.sleep(1)
    err = sys.exc_info()
    await errorChannel.send("%s\n```%s\n\n%s```"%(mateuszdrwal.mention,"".join(traceback.format_tb(err[2])),err[1].args[0]))
    logger.warn("".join(traceback.format_tb(err[2])),err[1].args[0])

async def startup():
    global http, conn, c
    http = aiohttp.ClientSession()

    conn = sqlite3.connect("requests.db")
    c = conn.cursor()


client.loop.create_task(startup())
client.loop.create_task(loop())
client.loop.create_task(backup())
client.loop.create_task(errorCatcher(cupTask(
                                             377230334288330753
                                             #390482469469552643
                                             ,"cup","/play/v1/leagues?types=&states={}&skill_levels=&limit.total=8&path=%2Fplay%2Fechoarena%2Feurope%2F&portals=&tags=vrclechoarena-eu-portal&includeHidden=0")))
client.loop.create_task(errorCatcher(cupTask(350354518502014976,"week","/play/v1/leagues?types=&states=inProgress,upcoming&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrclechoarena-na-portal&includeHidden=0")))
client.loop.create_task(client.start(secrets["discord token"]))




redirect = "http://178.62.89.61/auth"

routes = web.RouteTableDef()
app = web.Application(loop=client.loop)
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('./templates'))

def who(session, request):
    return "%s (%s)"%(session["username"], request.remote) if "username" in session else request.remote

@routes.get("/")
@aiohttp_jinja2.template("home.html")
async def home(request):
    session = await get_session(request)
    return {"error": request.query.get("error", None), "success": request.query.get("success", None), **session}

@routes.get("/requests")
@aiohttp_jinja2.template("requests.html")
async def requests(request):
    session = await get_session(request)
    try:
        assert "sort" in request.query and "filter" in request.query
        assert 0 <= int(request.query["sort"]) < 4 and 0 <= int(request.query["filter"]) < 8
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    except ValueError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    sort = int(request.query["sort"])
    if sort == 0:
        sort = "up-down DESC"
    elif sort == 1:
        sort = "up-down ASC"
    elif sort == 2:
        sort = "created DESC"
    elif sort == 3:
        sort = "created ASC"

    filt = int(request.query["filter"])
    if filt == 0:
        filt = ""
    elif filt == 1:
        filt = " AND status = 1"
    elif filt == 2:
        filt = " AND status = 3"
    elif filt == 3:
        filt = " AND status = 2"
    elif filt == 4:
        filt = " AND status = 0"
    elif filt == 5:
        filt = " AND up-down > 0"
    elif filt == 6:
        filt = " AND up-down < 0"
    elif filt == 7:
        filt = " AND status = 4"
    
    if request.query.get("request","null") == "null":
        c.execute("SELECT * FROM requests WHERE disabled = 0%s ORDER BY %s"%(filt, sort))
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
                             "mid": request[9],
                             "uid": request[10],
                             "vote": {},
                             "devresp": request[11],
                             "self": int(request[10]) == int(session.get("id",0))
                             } for request in fetched}
    
    votes = []
    if "username" in session:
        c.execute("SELECT * FROM votes WHERE uid = :uid", {"uid": session["id"]})
        fetched = c.fetchall()
        for vote in fetched:
            if vote[0] not in requests: continue
            requests[vote[0]]["vote"]["up"] = vote[2]
            requests[vote[0]]["vote"]["down"] = vote[3]
            requests[vote[0]]["vote"]["upDiscord"] = vote[4]
            requests[vote[0]]["vote"]["downDiscord"] = vote[5]

    return {"requests":[request for request in requests.values()], "admin": session.get("admin", False)}

@routes.get("/login")
async def login(request):
    return web.HTTPFound("https://discordapp.com/api/oauth2/authorize?client_id=427817724966600705&redirect_uri=http%3A%2F%2F178.62.89.61%2Fauth&response_type=code&scope=identify")

@routes.get("/auth")
async def auth(request):
    try:
        if "code" not in request.query:
            return web.HTTPFound("/")
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
        assert "access_token" in response
        response = json.loads(await get("https://discordapp.com/api/users/@me", {"Authorization": "Bearer %s"%response["access_token"]}))
        assert "username" in response
        session = await get_session(request)
        session["username"] = response["username"]
        session["id"] = response["id"]
        session["avatar"] = "https://cdn.discordapp.com/avatars/%s/%s.png?size=32"%(response["id"], response["avatar"])

        member = guild.get_member(int(response["id"]))
        if member != None and discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or member == mateuszdrwal, member.roles) != None:
            session["admin"] = True
            logger.info("admin %s logged in"%response["username"])
        else:
            session["admin"] = False
            logger.info("%s logged in"%response["username"])
        return web.HTTPFound("/")
    except AssertionError:
        logger.warn("error when logging in %s. queries: %s discord api response: %s"%(request.remote, request.query, response))
        return web.HTTPFound("/?error=An+error+has+occurred+while+trying+to+log+in.+Please+try+again.+If+the+issue+persists+please+PM+me%2C+mateuszdrwal%239960")

@routes.get("/logout")
async def logout(request):
    session = await get_session(request)
    if "username" in session:
        logger.info("%s logging out"%session["username"])
    else:
        logger.warn("%s logging out without being logged in"%request.remote)
    session.invalidate()
    return web.HTTPFound("/")

@routes.get("/vote")
async def vote(request):
    try:
        session = await get_session(request)
        if session.get("username") == None: return web.HTTPFound("/login") #redirect if not logged in
        assert "id" in request.query and "target" in request.query and "up" in request.query #all queries are present
        assert len(request.query["id"]) == 18 and request.query["target"] in ["0","1"] and request.query["up"] in ["0","1"] #query data is valid
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
        await updateRequest(await requestChannel.get_message(request.query["id"]))
        logger.info("%s %svoted %s setting %svote"%(session["username"], "" if int(request.query["target"]) else "un", request.query["id"], "up" if int(request.query["up"]) else "down"))
        return web.Response(text="OK")
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    except ValueError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

@routes.post("/newrequest")
async def newrequest(request):
    data = await request.post()
    session = await get_session(request)
    try:
        assert "title" in data and "type" in data and "category" in data and "description" in data
        assert len(data["title"]) <= 100 and len(data["type"]) <= 100 and len(data["category"]) <= 100 and len(data["description"]) <= 2000
        assert "username" in session
        assert client.get_user(int(session["id"])) != None
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    
    user = client.get_user(int(session["id"]))
    message = await requestChannel.send("New request submitted from website by %s:\n\n**Title**: %s\n**What kind of submission is this?**: %s\n**Category**: %s\n**Description**: %s"%(user.mention, data["title"], data["type"], data["category"], data["description"]))
    c.execute("INSERT INTO requests VALUES (:created, :author, :type, :title, :category, :description, 0, 0, 0, :mid, :uid, '', 0, 0)", {"created": time.time(), "author": "%s#%s"%(user.name, user.discriminator), "type": data["type"], "title": data["title"], "category": data["category"], "description": data["description"], "mid": message.id, "uid": user.id})
    conn.commit()
    logger.info("%s created a request titled \"%s\""%(session["username"], data["title"]))
    return web.HTTPFound("/?success=Request%20created%21")

@routes.post("/devresp")
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
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    except ValueError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("INSERT INTO responses VALUES (:mid, 0, :resp, :author)", {"mid": data["id"], "resp": data["devresp"], "author": session["username"]})
    conn.commit()
    await updateRequest(await requestChannel.get_message(data["id"]))
    logger.info("%s responded to %s"%(session["username"], data["id"]))
    return web.Response(text="OK")

@routes.get("/remove")
async def remove(request):
    session = await get_session(request)
    try:
        assert "id" in request.query
        assert len(request.query["id"]) == 18
        int(request.query["id"])
        assert "username" in session
        assert session["admin"]
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    except ValueError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("UPDATE requests SET disabled = 1 WHERE mid = :mid", {"mid": request.query["id"]})
    conn.commit()
    logger.info("%s removed %s"%(session["username"], request.query["id"]))
    return web.Response(text="OK")

@routes.get("/status")
async def status(request):
    session = await get_session(request)
    try:
        assert "id" in request.query and "target" in request.query
        assert len(request.query["id"]) == 18
        int(request.query["id"])
        assert "username" in session
        assert session["admin"]
        int(request.query["target"])
        assert 0 <= int(request.query["target"]) < 5
    except AssertionError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()
    except ValueError:
        logger.warning("%s is being suspicious"%who(session, request))
        return web.HTTPBadRequest()

    c.execute("UPDATE requests SET status = :status, webStatus = :webStatus WHERE mid = :mid", {"status": request.query["target"], "webStatus": 1 if int(request.query["target"]) != 0 else 0,"mid": request.query["id"]})
    conn.commit()
    logger.info("%s updated status of %s to %s"%(session["username"], request.query["id"], ["Open","Planned","Rejected","Implemented","Not applicable anymore"][int(request.query["target"])]))
    return web.Response(text="OK")

app.router.add_static("/static","static")
setup(app, EncryptedCookieStorage(open("cookiekey", "rb").readline()))
app.add_routes(routes)
web.run_app(app,port=80)