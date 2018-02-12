import discord, asyncio, pygsheets, datetime, re, time
from oauth2client.service_account import ServiceAccountCredentials

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
commentpattern = re.compile("(\d{18}) *?([\s\S]*)")

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
                for reaction in message.reactions:
                    if reaction.emoji == "\u26d4":
                        if await perm(reaction):
                            cont = True
                            break
                    elif reaction.emoji == "\U0001f44d":
                        upvotes = reaction.count
                        async for user in reaction.users():
                            if reaction.message.author == user:
                                upvotes -= 1
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
        
@client.event
async def on_ready():
    global requestChannel, guild
    
    print(client.user.name)
    print(client.user.id)

    requestChannel = client.get_channel(403335187062194188)
    matpmChannel = client.get_channel(412554371923050496)
    guild = client.get_guild(326412222119149578)

client.loop.create_task(loop())
client.run(open("token","r").read(), bot=False)
