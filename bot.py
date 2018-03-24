#!/usr/bin/env python3
import discord, asyncio, pygsheets, datetime, re, time, aiohttp, async_timeout, json, io, sys, traceback, sqlite3
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image, ImageFont, ImageDraw
from subprocess import Popen, PIPE

client = discord.Client()

vals = []
rejVals = []
doneVals = []
planVals = []

gs = pygsheets.authorize(service_file="key.json")

ss = gs.open("Echo Arena Feature Requests testing")
allS = ss.worksheet_by_title("All")
openS  = ss.worksheet_by_title("Open")
rejS  = ss.worksheet_by_title("Rejected")
doneS  = ss.worksheet_by_title("Implemented")
planS  = ss.worksheet_by_title("Planned")
stats = ss.worksheet_by_title("Stats")

pattern = re.compile(r"\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")
commentpattern = re.compile("(\d{18})[^>].*?([^\s:-][\s\S]*)")

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
    global vals, rejVals, doneVals, planVals, c
    
    for sheet, criteria in [(openS, " WHERE status = 0"),(planS, " WHERE status = 1"),(rejS, " WHERE status = 2"),(doneS, " WHERE status = 3"),(allS, "")]:

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
    
    vals = []
    rejVals = []
    doneVals = []
    planVals = []

async def loop():
    global requestChannel, vals, rejVals, doneVals, planVals, guild, conn, c
    await client.wait_until_ready()
    await asyncio.sleep(1)
    while True:
        try:
            start = time.time()

            
            async for message in requestChannel.history(limit=None, reverse=True):
                
                results = re.findall(pattern, message.clean_content)
                comment = re.findall(commentpattern, message.content)
                
                if comment != [] and message.author not in guild.members: continue
                if comment != [] and discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or message.author.name == "mateuszdrwal", message.author.roles) != None:
                    comment = comment[0]
                    id = int(comment[0])

                    c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": id})

                    if c.fetchall() != []:
                        c.execute("SELECT * FROM responses WHERE rmid = :rmid", {"rmid":message.id})

                        if c.fetchall() == []:
                            c.execute("INSERT INTO responses VALUES (:mid, :rmid, :resp)",{"mid": id, "rmid": message.id, "resp": comment[1]})
                            conn.commit()
                            await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")
                        else:
                            c.execute("UPDATE responses SET response = :resp WHERE mid = :mid AND rmid = :rmid",{"mid": id, "rmid": message.id, "resp": comment[1]})
                        
##                    for array in [vals, rejVals, doneVals]:
##                        msg = discord.utils.find(lambda r: r["mid"] == id, array)
##                        if msg != None:
##                            msg["devresp"].append(comment[1])
##                            await message.add_reaction(u"\N{WHITE HEAVY CHECK MARK}")
##                            break
                    continue
                    
                if results == [] or message.id == 403337281068466197:
                    continue



                upvotes = 0
                downvotes = 0
                status = 0 #0: open, 1: in-progress, 2: rejected, 3: resolved
                cont = False
                #voted = []

                c.execute("SELECT * FROM votes WHERE mid = :mid", {"mid": message.id})
                fetched = c.fetchall()
                uped = [vote[1] for vote in fetched if vote[2] and vote[4]]
                downed = [vote[1] for vote in fetched if vote[3] and vote[5]]
                
                for reaction in message.reactions:
                    if reaction.emoji == "\u26d4":
                        if await perm(reaction):
                            c.execute("DELETE FROM requests WHERE mid = :mid", {"mid": message.id})
                            c.execute("DELETE FROM votes WHERE mid = :mid", {"mid": message.id})
                            c.execute("DELETE FROM responses WHERE mid = :mid", {"mid": message.id})
                            conn.commit()
                            cont = True
                            break
                        
                    elif reaction.emoji == "\U0001f5d3":
                        if await perm(reaction) and status < 1:
                            status = 1
                    elif reaction.emoji == "\u274c":
                        if await perm(reaction) and status < 2:
                            status = 2
                    elif reaction.emoji == "\u2705":
                        if await perm(reaction) and status < 3:
                            status = 3

                    elif reaction.emoji == "\U0001f44e":
                        async for user in reaction.users():
                            if reaction.message.author == user:
                                continue

                            c.execute("SELECT * FROM votes WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                            fetched = c.fetchall()
                            if fetched != []:
                                if fetched[0][3] != 1 or fetched[0][5] != 1:
                                    c.execute("UPDATE votes SET down = 1 AND downDiscord = 1 WHERE :mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                            else:
                                c.execute("INSERT INTO votes VALUES (:mid, :uid, 0, 1, 0, 1)", {"mid": message.id, "uid": user.id})

                            conn.commit()
                            
                            try:
                                downed.remove(user.id)
                            except ValueError:
                                pass
                        #downvotes = reaction.count
                        
                    elif reaction.emoji in ["\U0001f44d","\U0001F60D","\u2764","\u261D","\U0001F446","\U0001F44C","\U0001F4AF"]:
                        async for user in reaction.users():
                            if reaction.message.author == user:
                                continue

                            c.execute("SELECT * FROM votes WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                            fetched = c.fetchall()
                            if fetched != []:
                                if fetched[0][2] != 1 or fetched[0][4] != 1:
                                    c.execute("UPDATE votes SET up = 1 AND upDiscord = 1 WHERE :mid = :mid AND uid = :uid", {"mid": message.id, "uid": user.id})
                            else:
                                c.execute("INSERT INTO votes VALUES (:mid, :uid, 1, 0, 1, 0)", {"mid": message.id, "uid": user.id})

                            conn.commit()
                            
                            try:
                                uped.remove(user.id)
                            except ValueError:
                                pass
    
                            #voted.append(user)
                            #upvotes += 1
                            
                if cont:
                    continue

                for user in uped:
                    c.execute("UPDATE votes SET up = 0 AND upDiscord = 0 WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user})
                for user in downed:
                    c.execute("UPDATE votes SET down = 0 AND downDiscord = 0 WHERE mid = :mid AND uid = :uid", {"mid": message.id, "uid": user})
                conn.commit()

                c.execute("SELECT count(*) FROM votes WHERE up = 1 AND mid = :mid", {"mid": message.id})
                upvotes = c.fetchall()[0][0]
                c.execute("SELECT count(*) FROM votes WHERE down = 1 AND mid = :mid", {"mid": message.id})
                downvotes = c.fetchall()[0][0]

                c.execute("SELECT * FROM requests WHERE mid = :mid", {"mid": message.id})
                fetched = c.fetchall()
                if fetched != []:
                    c.execute("""UPDATE requests SET
                    author = :author,
                    sugType = :sugType,
                    title = :title,
                    category = :category,
                    description = :description,
                    up = :up,
                    down = :down,
                    status = :status
                    WHERE mid = :mid""", {
                        "author": "%s#%s"%(message.author.name, message.author.discriminator),
                        "sugType": results[0][0],
                        "title": results[0][1],
                        "category": results[0][2],
                        "description": results[0][3],
                        "up": upvotes,
                        "down": downvotes,
                        "status": status,
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
                    :up,
                    :down,
                    :status,
                    :mid,
                    :uid
                    )""", {
                        "time": message.created_at.timestamp(),
                        "author": "%s#%s"%(message.author.name, message.author.discriminator),
                        "sugType": results[0][0],
                        "title": results[0][1],
                        "category": results[0][2],
                        "description": results[0][3],
                        "up": upvotes,
                        "down": downvotes,
                        "status": status,
                        "mid": message.id,
                        "uid": message.author.id
                        })

                conn.commit()
                
##                entry = {"time": message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
##                        "author": "%s#%s"%(message.author.name, message.author.discriminator),
##                        "type": results[0][0],
##                        "title": results[0][1],
##                        "category": results[0][2],
##                        "description": results[0][3],
##                        "points": str(upvotes-downvotes),
##                        "upvotes": str(upvotes),
##                        "downvotes": str(downvotes),
##                        "status": status,
##                        "devresp": [],
##                        "mid": message.id,
##                        "aid": message.author.id
##                        }

##                sugType = results[0][0].lower()
##
##                if status == 1:
##                    planVals.append(entry)
##                elif status == 2:
##                    rejVals.append(entry)
##                elif status == 3:
##                    doneVals.append(entry)
##                else:
##                    vals.append(entry)
            
            updateSheet()
            end = time.time()
            print("updated %ss"%round(end-start,3))
            await asyncio.sleep(600)

        except Exception as error:
            raise error
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

            teamList = []
            for team in raw:
                if team["status"] == "checkedIn":
                    players = await eslApi("/play/v1/teams/%s/members"%team["id"])
                    teamList.append([team["seed"], team["name"], ", ".join([player["user"]["nickname"] for player in players.values() if player["membership"]["role"] != "inactive"])])
            teamList.sort()
                            
            await cupChannel.send("The weekly cup has begun! Good luck to everyone participating!")
            await cupChannel.send("Here are the seeds participating today:\n\n%s"%"\n".join(["**%s. %s**\n    *%s*"%(i, name[1], name[2]) for i, name in enumerate(teamList)]))

        raw = await eslApi("/play/v1/leagues/%s/contestants"%cup[1])

        pixlim = 128*3

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
    global requestChannel, guild, http, errorChannel, mateuszdrwal, conn, c
    
    print(client.user.name)
    print(client.user.id)

    requestChannel = client.get_channel(403335187062194188)
    matpmChannel = client.get_channel(412554371923050496)
    errorChannel = client.get_channel(424701844942618634)

    mateuszdrwal = client.get_user(140504440930041856)
    guild = client.get_guild(326412222119149578)

    http = aiohttp.ClientSession()

    conn = sqlite3.connect("requests.db")
    c = conn.cursor()

    await client.change_presence(game=discord.Game(name='Echo Combat',type=1))

async def errorCatcher(task):
    global errorChannel, mateuszdrwal
    try:
        await task
    except Exception as e:
        err = sys.exc_info()
        await errorChannel.send("%s\n```%s\n\n%s```"%(mateuszdrwal.mention,"".join(traceback.format_tb(err[2])),err[1].args[0]))

client.loop.create_task(loop())
client.loop.create_task(errorCatcher(cupTask(
    377230334288330753
    #390482469469552643
                                             ,"cup","/play/v1/leagues?types=&states={}&skill_levels=&limit.total=8&path=%2Fplay%2Fechoarena%2Feurope%2F&portals=&tags=vrclechoarena-eu-portal&includeHidden=0")))
client.loop.create_task(errorCatcher(cupTask(350354518502014976,"week","/play/v1/leagues?types=&states=inProgress,upcoming&path=%2Fplay%2Fechoarena%2F&portals=&tags=vrclechoarena-na-portal&includeHidden=0")))
client.run(open("token","r").read())
