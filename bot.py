#!/usr/bin/env python3
import discord, asyncio, pygsheets, datetime, re, time, aiohttp, async_timeout, json, io
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image, ImageFont, ImageDraw
from subprocess import Popen, PIPE

client = discord.Client()

reqVals = []
featVals = []
rejVals = []
doneVals = []
planVals = []

gs = pygsheets.authorize(service_file="key.json")

ss = gs.open("Echo Arena Feature Requests")
allS = ss.worksheet_by_title("All")
openS  = ss.worksheet_by_title("Open")
rejS  = ss.worksheet_by_title("Rejected")
doneS  = ss.worksheet_by_title("Implemented")
planS  = ss.worksheet_by_title("Planned")
stats = ss.worksheet_by_title("Stats")

pattern = re.compile(r"\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
commentpattern = re.compile("(\d{18}).*?([^\s:-][\s\S]*)")

async def perm(reaction):
    global guild
    async for user in reaction.users():
        try:
            member = guild.get_member(user.id)
            if discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or member.name == "mateuszdrwal", member.roles) != None:
                return True                             
        except:
            return False

def updateSheet():
    global reqVals, featVals, rejVals, doneVals, planVals
    

    for sheet, entries in [(openS, featVals+reqVals),(doneS, doneVals),(planS,planVals),(allS, reqVals+featVals+rejVals+doneVals+planVals)]:
        #if len(entries) == 0:
        #continue
        
        newVals = []
        
        for entry in entries:
            if entry["status"] == 0:
                status = "Open"
            if entry["status"] == 1:
                status = "Planned"
            if entry["status"] == 2:
                status = "Rejected"
            if entry["status"] == 3:
                status = "Implemented"

            newVals.append([entry["time"],
                            entry["author"],
                            entry["type"],
                            entry["title"],
                            entry["category"],
                            entry["description"],
                            entry["points"],
                            entry["upvotes"],
                            entry["downvotes"],
                            status,
                            "\n\n".join(entry["devresp"]),
                            entry["mid"],
                            entry["aid"]
                            ])
        
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
    
    reqVals = []
    featVals = []
    rejVals = []
    doneVals = []
    planVals = []

async def loop():
    global requestChannel, reqVals, featVals, rejVals, doneVals, planVals, guild
    await client.wait_until_ready()
    await asyncio.sleep(1)
    while True:
        try:
            start = time.time()

            
            async for message in requestChannel.history(limit=None, reverse=True):
                
                results = re.findall(pattern, message.content)
                comment = re.findall(commentpattern, message.content)
                if comment != [] and message.author not in guild.members: continue
                if comment != [] and discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or message.author.name == "mateuszdrwal", message.author.roles) != None:
                    comment = comment[0]
                    id = int(comment[0])
                    for array in [reqVals, featVals, rejVals, doneVals]:
                        msg = discord.utils.find(lambda r: r["mid"] == id, array)
                        if msg != None:
                            msg["devresp"].append(comment[1])
                            await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")
                            break
                    continue
                    
                if results == [] or message.id == 403337281068466197:
                    continue

                upvotes = 0
                downvotes = 0
                status = 0 #0: open, 1: in-progress, 2: rejected, 3: resolved
                cont = False
                voted = []
                for reaction in message.reactions:
                    if reaction.emoji == "\u26d4":
                        if await perm(reaction):
                            cont = True
                            break
                    elif reaction.emoji == "\U0001f44e":
                        downvotes = reaction.count

                    elif reaction.emoji == "\U0001f5d3":
                        if await perm(reaction) and status < 1:
                            status = 1
                    elif reaction.emoji == "\u274c":
                        if await perm(reaction) and status < 2:
                            status = 2
                    elif reaction.emoji == "\u2705":
                        if await perm(reaction) and status < 3:
                            status = 3
                    elif reaction.emoji in ["\U0001f44d","\U0001F60D","\u2764","\u261D","\U0001F446","\U0001F44C","\U0001F4AF"]:
                        async for user in reaction.users():
                            if user in voted or reaction.message.author == user:
                                continue
                            voted.append(user)
                            upvotes += 1
                            
                if cont:
                    continue

                entry = {"time": message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "author": "%s#%s"%(message.author.name, message.author.discriminator),
                        "type": results[0][0],
                        "title": results[0][1],
                        "category": results[0][2],
                        "description": results[0][3],
                        "points": str(upvotes-downvotes),
                        "upvotes": str(upvotes),
                        "downvotes": str(downvotes),
                        "status": status,
                        "devresp": [],
                        "mid": message.id,
                        "aid": message.author.id
                        }

                sugType = results[0][0].lower()

                if status == 1:
                    planVals.append(entry)
                elif status == 2:
                    rejVals.append(entry)
                elif status == 3:
                    doneVals.append(entry)
                elif "feature" in sugType and ("request" in sugType or "new" in sugType):
                    reqVals.append(entry)
                elif "improv" in sugType and "existing" in sugType and "feature" in sugType:
                    featVals.append(entry)

            updateSheet()
            end = time.time()
            print("updated %ss"%round(end-start,3))
            await asyncio.sleep(600)

        except Exception as error:
            print(error)
            gs = pygsheets.authorize(service_file="key.json")

            ss = gs.open("Echo Arena Feature Requests")
            allS = ss.worksheet_by_title("All")
            openS  = ss.worksheet_by_title("Open")
            rejS  = ss.worksheet_by_title("Rejected")
            doneS  = ss.worksheet_by_title("Implemented")
            planS  = ss.worksheet_by_title("Planned")
            stats = ss.worksheet_by_title("Stats")

async def cupTask(cupChannel, textInCup, link):
    
    await client.wait_until_ready()
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
            print("waiting %s"%waitTime)
            await asyncio.sleep(waitTime)

            raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])
            teamList = [[team["seed"], team["name"]] for team in raw if team["status"] == "checkedIn"]
            teamList.sort()
                            
            await cupChannel.send("The weekly cup has begun! Good luck to everyone participating!")
            await cupChannel.send("Here are the seeds participating today:```%s```"%"\n".join(["%s. %s"%(i+1, name[1]) for i, name in enumerate(teamList)]))

        raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

        pixlim = 128*3

        try:
            open("tempFile", "r").close()
        except FileNotFoundError:
            open("tempFile","w").close()

        allcups = []

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
                f = open("tempFile","r")
                ids = f.readlines()
                f.close()

                ended = pairing["calculatedAt"]
                teams2 = [pairing["contestants"][0]["team"]["name"],pairing["contestants"][1]["team"]["name"]]
                points = [pairing["result"]["score"].get(pairing["contestants"][0]["team"]["id"]),pairing["result"]["score"].get(pairing["contestants"][1]["team"]["id"])]

                if pairing["status"] != "closed" or str(pairing["id"])+"\n" in ids:
                    continue

                if points[0] == None or points[1] == None or ended == None:
                    f = open("tempFile","a")
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

                f = open("tempFile","a")
                f.write(str(pairing["id"])+"\n")
                f.close()

            f = open("tempFile","r")
            ids = f.readlines()
            f.close()
            for pairing in pairings:
                if str(pairing["id"])+"\n" not in ids:
                    break
            else:
                if time.time() - cup[0] > 7200 and await eslApi("/play/v1/leagues?types=&states=inProgress&skill_levels=&limit.total=8&path=%2Fplay%2Fechoarena%2Feurope%2F&portals=&tags=vrclechoarena-eu-portal&includeHidden=0") == {}:
                    break

        Popen(["rm","tempFile"])
        await cupChannel.send("The cup has now ended! Good job everyone!")
        await cupChannel.send("Here are the final rankings of todays cup:")

        for cup2 in allcups:
            ranking = await eslApi("/play/v1/leagues/%s/ranking"%cup2)
            if ranking["ranking"] == None:
                continue
            teams2 = [(team["position"], team["team"]["name"]) for team in ranking["ranking"]]
            teams2.sort()
            await cupChannel.send("```%s```"%"\n".join(["%s. %s"%(team[0],team[1]) for team in teams2]))
        
        print("cup done")
        await asyncio.sleep(3600*12)

async def eslApi(path):
    raw = await request("https://api.eslgaming.com"+path)
    return json.loads(raw)

async def request(url):
    global http
    while True:
        try:
            with async_timeout.timeout(30):
                async with http.get(url) as response:
                    return await response.text()
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
    global requestChannel, guild, http
    
    print(client.user.name)
    print(client.user.id)

    requestChannel = client.get_channel(403335187062194188)
    matpmChannel = client.get_channel(412554371923050496)
    guild = client.get_guild(326412222119149578)

    http = aiohttp.ClientSession()


client.loop.create_task(loop())
client.loop.create_task(cupTask(377230334288330753,"cup","/play/v1/leagues?types=&states={}&skill_levels=&limit.total=8&path=%2Fplay%2Fechoarena%2Feurope%2F&portals=&tags=vrclechoarena-eu-portal&includeHidden=0"))
client.loop.create_task(cupTask(350354518502014976,"week","/play/v1/leagues?types=&states=inProgress,upcoming&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrclechoarena-na-portal&includeHidden=0"))
client.run(open("token","r").read())
