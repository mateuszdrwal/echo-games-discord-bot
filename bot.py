import discord, asyncio, gspread, datetime, re, time
from oauth2client.service_account import ServiceAccountCredentials

client = discord.Client()

reqVals = []
featVals = []
otherVals = []

pattern = re.compile(r"\*?\*?What kind of submission is this\?[\*,:, ]*(.*?) ?\n\n?\*?\*?Title[\*,:, ]*(.*?) ?\n\*?\*?Category[\*,:, ]*(.*?) ?\n\*?\*?Description[\*,:, ]*([\s\S]*)")

def updateSheet():
    global sheet, reqVals, featVals, otherVals
    credentials = ServiceAccountCredentials.from_json_keyfile_name('./key.json', ['https://spreadsheets.google.com/feeds'])
    gs = gspread.authorize(credentials)

    ss = gs.open("Echo Arena Feature Requests")
    s1 = ss.worksheet("Feature Request")
    s2 = ss.worksheet("Improving an Existing Feature")
    s3 = ss.worksheet("Other")
    s4 = ss.worksheet("All")

    for sheet, newVals in [(s1, reqVals),(s2, featVals), (s3, otherVals), (s4, reqVals+featVals+otherVals)]:
        if len(newVals) == 0:
            continue
        newVals.sort(key=lambda x: int(x[6]))
        newVals.reverse()
        cells = sheet.range(2,1,len(newVals)+1,11)
        for cell in cells:
            cell.value = newVals[cell.row-2][cell.col-1]

        sheet.update_cells(cells)                
    
    reqVals = []
    featVals = []
    otherVals = []

async def loop():
    global requestChannel, reqVals, featVals, otherVals, guild
    await client.wait_until_ready()
    await asyncio.sleep(1)
    while True:
        try:
            start = time.time()
            
            async for message in requestChannel.history(limit=1000,reverse=True):
                
                results = re.findall(pattern, message.content)
                if results == [] or message.id == 403337281068466197:
                    continue

                upvotes = 0
                downvotes = 0
                cont = False
                for reaction in message.reactions:
                    if reaction.emoji == "\u26d4":
                        async for user in reaction.users():
                            try:
                                member = guild.get_member(user.id)
                                if discord.utils.find(lambda r: r.name == "Moderator" or r.name == "Developer" or member.name == "mateuszdrwal", member.roles) != None:
                                    cont = True
                                    break                                
                            except:
                                pass
                        if cont:
                            break
                    elif reaction.emoji == "\U0001f44d":
                        upvotes = reaction.count
                        async for user in reaction.users():
                            if reaction.message.author == user:
                                upvotes -= 1
                    elif reaction.emoji == "\U0001f44e":
                        downvotes = reaction.count

                if cont:
                    continue

                entry = [message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "%s#%s"%(message.author.name, message.author.discriminator),
                        results[0][0],
                        results[0][1],
                        results[0][2],
                        results[0][3],
                        str(upvotes-downvotes),
                        str(upvotes),
                        str(downvotes),
                        message.id,
                        message.author.id
                        ]

                sugType = results[0][0].lower()
                if "feature" in sugType and ("request" in sugType or "new" in sugType):
                    reqVals.append(entry)
                elif "improv" in sugType and "existing" in sugType and "feature" in sugType:
                    featVals.append(entry)
                else:
                    otherVals.append(entry)

            updateSheet()
            end = time.time()
            print("updated %ss"%round(end-start,3))
            await asyncio.sleep(600)

        except Exception as error:
            print(error)
        
@client.event
async def on_ready():
    global requestChannel, guild
    
    print(client.user.name)
    print(client.user.id)

    requestChannel = client.get_channel(403335187062194188)
    guild = client.get_guild(326412222119149578)

client.loop.create_task(loop())
client.run(open("token","r").read(), bot=False)
