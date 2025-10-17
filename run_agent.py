from app.agent.graph import invoke
s = invoke("summarize demo", profile="work")
print(s.result, s.cites)
