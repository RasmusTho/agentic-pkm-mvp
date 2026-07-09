# Transcript: Skill Issue: Andrej Karpathy on Code Agents, AutoResearch, and the Loopy Era of AI

State: Supporting evidence transcript (advisory research corpus)

- Video ID: `kwSVtQ7dziU`
- URL: https://youtu.be/kwSVtQ7dziU?si=whmTl3zrC4pZieSH
- Channel: No Priors: AI, Machine Learning, Tech, & Startups
- Publish date: 20260320
- Duration seconds: 3991
- Metadata language: `en`
- Caption language: `en`
- Acquisition method: `captions_auto`
- Selection path: `pipeline_selector`
- Quality note: machine-generated auto-captions; rolling-cue duplication removed by normalization, punctuation/segmentation may still be imprecise
- Content identity: `sha256:e380a3f361fd582779cf8402ff218dda57c58fd895ae0b7e23a273ee769d78a3`

## Chapters

- 0.0: Andrej Karpathy Introduction
- 175.0: What Capability Limits Remain?
- 375.0: What Mastery of Coding Agents Looks Like
- 676.0: Second Order Effects of Natural Language Coding
- 951.0: Why AutoResearch
- 1365.0: Relevant Skills in the AI Era
- 1705.0: Model Speciation
- 1950.0: Building More Collaboration Surfaces for Humans and AI
- 2248.0: Analysis of Jobs Market Data
- 2905.0: Open vs. Closed Source Models
- 3231.0: Autonomous Robotics
- 3659.0: MicroGPT and Agentic Education
- 3940.0: Conclusion

## Normalized Transcript

[1.870-1.880] Code's not even the right verb anymore,
[1.880-3.630] right? [laughter] But I have to
[3.640-6.230] express my will to my agents for 16
[6.240-7.750] hours a day. Manifest. [music]
[7.760-9.270] How can I have not just a single session
[9.280-10.870] of Claude code or Codex or some of these
[10.880-12.550] agent harnesses? How can I have more of
[12.560-14.630] them? How can I do that appropriately?
[14.640-16.470] The agent part is now taken for granted.
[16.480-18.070] Now the claw-like entities are taken for
[18.080-19.630] granted and now you can have multiple of
[19.640-21.110] them and now you can have instructions
[21.120-22.230] to them and now you can have
[22.240-23.990] optimization over the instructions. But
[24.000-24.225] there
[24.235-24.470] &gt;&gt; [laughter]
[24.480-25.350] &gt;&gt; I mean this is why it gets to the
[25.360-27.070] psychosis is that this is like infinite
[27.080-34.790] and everything is a skill issue.
[36.990-37.000] Hi listeners, welcome back to No Priors.
[37.000-38.790] Today I'm here with Andre Karpathy and
[38.800-40.470] we have a wide-ranging conversation for
[40.480-42.990] you about code agents, the future of
[43.000-45.150] engineering and AI research, how more
[45.160-47.190] people can contribute to research,
[47.200-49.150] what's happening in robotics, his
[49.160-51.080] prediction for how agents can reach out
[51.090-53.070] [music] into the real world, and
[53.080-55.230] education in this next age. Welcome,
[55.240-56.190] Andre.
[56.200-57.750] Andre, thanks for doing this. Yeah,
[57.760-59.070] thank you for having me.
[59.080-61.030] Uh so it's been a very exciting couple
[61.040-63.430] of months in AI. Uh yeah, you could say
[63.440-63.790] that.
[63.800-67.150] &gt;&gt; I remember um walking into the office at
[67.160-68.230] some point and you were like really
[68.240-70.350] locked in and I was asking what you were
[70.360-71.670] up to and you're like, I just I have to
[71.680-73.590] code for 16 hours a day or code's not
[73.600-75.510] even the right verb anymore, right? But
[75.520-76.670] I have to
[76.680-79.430] um express my will to my agents for 16
[79.440-81.590] hours a day. Manifest
[81.600-83.990] um because like there's been a jump in
[84.000-85.630] capability.
[85.640-86.910] Uh what's happening? Tell me about your
[86.920-88.750] experience. Yeah, I kind of feel like I
[88.760-90.510] was just in this perpetual I still am
[90.520-92.790] often in this state of AI psychosis just
[92.800-94.790] like all the time um because there was a
[94.800-96.190] huge unlock in what you can achieve as a
[96.200-97.790] person as an individual, right? Because
[97.800-99.310] you were bottlenecked by, you know, your
[99.320-101.230] typing speed and so on. But now with
[101.240-102.950] these agents it really, I would say in
[102.960-105.150] December is when it really just
[105.160-106.710] something flipped where I kind of went
[106.720-109.030] from 80/20 of like, you know, uh to like
[109.040-111.350] 20/80 of writing code by myself versus
[111.360-112.990] just delegating to agents. And I don't
[113.000-114.350] even think it's 20/80 by now. I think
[114.360-115.510] it's a lot more than that. I don't think
[115.520-118.350] I've typed like a line of code probably
[118.360-119.856] since December basically.
[119.866-120.590] &gt;&gt; [laughter]
[120.600-123.310] &gt;&gt; Um which is like an extremely large
[123.320-125.750] uh change. Um I was talking to it like
[125.760-127.510] for example, I was talking about it to
[127.520-129.310] for example my parents and so on and I
[129.320-130.190] don't think like a normal person
[130.200-131.670] actually realizes that this happened or
[131.680-133.670] how dramatic it was. Like literally like
[133.680-135.030] if you just find a random software
[135.040-136.470] engineer or something like that at their
[136.480-137.830] at their desk and what they're doing,
[137.840-139.990] like their default workflow of, you
[140.000-141.990] know, building software is completely
[142.000-144.550] different as of basically December.
[144.560-146.710] Uh so I'm just like in this state of
[146.720-148.430] psychosis of trying to figure out like
[148.440-150.350] what's possible, uh trying to push it to
[150.360-151.910] the limit. How is it how can I have not
[151.920-153.830] just a single session of, you know, um
[153.840-155.230] Claude code or Codex or some of these
[155.240-156.870] agent harnesses? How can I have more of
[156.880-158.430] them? How can I do that uh
[158.440-160.630] appropriately? And then how can I use
[160.640-163.070] these claws? What are these claws? Uh
[163.080-165.110] and uh so there's like a lot of new
[165.120-166.830] things. I want to be at the forefront of
[166.840-168.350] it, you know, and I'm very
[168.360-169.870] antsy that I'm not at the forefront of
[169.880-171.110] it and I see lots of people on Twitter
[171.120-172.190] doing all kinds of things and they all
[172.200-173.550] sound like really good ideas and I need
[173.560-174.870] to be at the forefront or I feel
[174.880-176.470] extremely nervous. And so I guess I'm
[176.480-178.070] just in this psychosis of like what's
[178.080-179.990] possible like because it's unexplored
[180.000-181.390] fundamentally. Well, if you're nervous,
[181.400-183.510] the rest of us are are nervous. We have
[183.520-185.750] a we have a team that we work with at
[185.760-188.870] Conviction that their setup is everybody
[188.880-190.990] is like, you know, none of the engineers
[191.000-193.350] write code by hand and they they're all
[193.360-194.910] microphoned and they just like whisper
[194.920-196.550] to their agents all the time. It's the
[196.560-198.910] strangest work setting ever.
[198.920-200.510] Uh and I thought they were crazy and now
[200.520-201.910] I like I fully accept I was like, oh
[201.920-203.470] this was the way. Like you're just ahead
[203.480-204.430] of it.
[204.440-206.230] Um what uh
[206.240-207.950] how do you think about your own capacity
[207.960-210.670] now to like explore or to do projects?
[210.680-212.710] Like what is it limited by?
[212.720-214.350] Yeah, what is it limited by? Uh just I
[214.360-216.470] think everything like so many things
[216.480-218.270] even if they don't work, I think to a
[218.280-219.590] large extent you feel like it's a skill
[219.600-221.030] issue. It's not that the capability is
[221.040-222.190] not there. It's that you just haven't
[222.200-224.310] found a way to string it together of
[224.320-225.950] what's available. Like I just don't I
[225.960-227.830] didn't give good enough instructions in
[227.840-229.910] the agents from the file or whatever it
[229.920-231.910] may be. I don't have a nice enough
[231.920-233.910] memory tool that I put in there or
[233.920-235.550] something like that. So it all kind of
[235.560-236.590] feels like skill issue when it doesn't
[236.600-238.150] work to some extent. You want to see how
[238.160-239.790] you can parallelize them etc. and you
[239.800-241.950] want to be Peter Steinberg basically. Uh
[241.960-243.750] so Peter is famous. He has a funny photo
[243.760-244.950] where he's in front of a monitor with
[244.960-247.390] lots of uh like he uses Codex. So lots
[247.400-250.030] of Codex agents tiling the the monitor
[250.040-251.350] and they all take about 20 minutes if
[251.360-252.830] you prompt them correctly and use the
[252.840-254.310] high effort. And so they all take about
[254.320-255.710] 20 minutes. They have multiple, you
[255.720-258.550] know, 10 repos checked out. And so he's
[258.560-260.670] just um going between them and giving
[260.680-262.230] them work. It's just like you can you
[262.240-264.270] can you can move in much larger macro
[264.280-265.710] actions. It's not just like here's a
[265.720-266.990] line of code, here's a new function.
[267.000-269.230] It's like here's a new functionality and
[269.240-270.590] delegate it to agent one. Here's a new
[270.600-271.470] functionality that's not going to
[271.480-272.790] interfere with the other one. Give it
[272.800-275.310] agent two. And then try to uh review
[275.320-277.058] their work as best as you can
[277.068-277.470] &gt;&gt; [laughter]
[277.480-278.430] &gt;&gt; depending on how much you care about
[278.440-279.990] that code. Like where are these macro
[280.000-281.750] actions that I can like manipulate my
[281.760-284.430] software repository by? And like another
[284.440-285.870] agent is doing some like research,
[285.880-287.310] another agent is writing code, another
[287.320-288.630] one is coming up with a plan for some
[288.640-290.310] new implementation. And so everything is
[290.320-291.950] just like happens in these like macro
[291.960-294.830] actions over your repository. Um and
[294.840-296.110] you're just trying to become like really
[296.120-297.590] good at it and develop like a muscle
[297.600-300.470] memory for it is extremely um
[300.480-301.830] Yeah, it's very rewarding number one
[301.840-303.310] because it actually works. Uh but it's
[303.320-304.350] also kind of like the new thing to
[304.360-306.070] learn. So that's why hence the
[306.080-307.390] psychosis.
[307.400-310.310] Yeah, I I do feel like my instinct is
[310.320-311.270] like
[311.280-312.870] whenever I'm waiting for an agent to
[312.880-314.270] complete something, the obvious thing to
[314.280-315.950] do is like, well, I can do more work,
[315.960-317.430] right? Like if I have access to more
[317.440-319.030] tokens then like I should just
[319.040-321.390] parallelize at tasks. And so that's
[321.400-323.430] that's very stressful because if you
[323.440-325.350] don't feel very bounded by your ability
[325.360-328.310] to spend on tokens, then you know, you
[328.320-329.990] are the bottleneck in the system that is
[330.000-331.390] max capability. Yeah, if you're not
[331.400-333.950] maximizing your subscription at least.
[333.960-334.710] And
[334.720-336.350] ideally for multiple agents. Like if you
[336.360-337.990] run out of the quota on Codex, you
[338.000-339.270] should switch to Claude or whatnot. I
[339.280-340.510] don't know. Like that's what I've been
[340.520-342.030] trying to do a little bit and I feel
[342.040-343.470] nervous when I have subscription left
[343.480-344.990] over. That just means I haven't
[345.000-347.030] maximized my token throughput. So I
[347.040-348.070] actually kind of experienced this when I
[348.080-349.310] was a PhD student. You would feel
[349.320-351.190] nervous when your GPUs are not running.
[351.200-352.470] Like you have GPU capability and you're
[352.480-354.110] not maximizing your the available flops
[354.120-355.630] to you. But now it's not about flops,
[355.640-356.950] it's about tokens.
[356.960-359.310] So what is your token throughput and
[359.320-361.350] what token throughput do you command? I
[361.360-362.670] would actually argue that it's very
[362.680-365.270] interesting that we had, you know, at
[365.280-367.950] least 10 years where
[367.960-369.710] in many engineering tasks people just
[369.720-371.950] did they didn't feel compute bound.
[371.960-374.190] Right? Um and now the entire industry
[374.200-376.350] feels that now. They feel like they they
[376.360-378.750] they felt resource bound uh
[378.760-380.550] and now that you have this big
[380.560-382.950] capability jump, you're like, oh,
[382.960-384.750] actually it's not, you know, my ability
[384.760-386.750] to access the computer anymore. Like I'm
[386.760-388.230] I'm the binding constraint. Yeah, it's a
[388.240-390.430] skill issue. Which is very empowering
[390.440-392.230] cuz um yeah, cuz you could be getting
[392.240-394.070] better. So that's why that's why I think
[394.080-395.350] it's very addictive because there's
[395.360-396.870] unlocks when you when you get better.
[396.880-398.430] Where do you think it goes? Like if you
[398.440-400.870] just think about like, okay, you know,
[400.880-402.750] Andre's iterating and everybody else is
[402.760-404.150] for 16 hours a day getting better at
[404.160-405.390] using coding agents. Like what does it
[405.400-406.710] look like in a year?
[406.720-408.714] Of like you've reached mastery.
[408.724-409.070] &gt;&gt; [laughter]
[409.080-410.150] &gt;&gt; Yeah, what does mastery look like,
[410.160-412.110] right? At the end of the year or like
[412.120-413.390] two, three years, five years, 10 years,
[413.400-414.630] etc.
[414.640-415.510] Well, I think everyone is basically
[415.520-417.870] interested in like going up the stack.
[417.880-419.630] So I would say it's yeah, it's not about
[419.640-421.910] a single session with your agent.
[421.920-423.270] Multiple agents, how do they collaborate
[423.280-425.070] and teams and so on. So everyone's
[425.080-425.990] trying to figure out what that looks
[426.000-427.430] like. And then I would say Claude is
[427.440-428.590] also kind of an interesting direction
[428.600-430.270] because it really, when I say a Claude,
[430.280-432.150] I mean this like layer that kind of
[432.160-433.950] takes persistence to a whole new level.
[433.960-435.470] Like it's something that like keeps
[435.480-437.430] looping. It's it's like um
[437.440-438.550] it's not something that you are
[438.560-440.190] interactively in the middle of. It kind
[440.200-442.190] of like has its own little sandbox, its
[442.200-443.390] own little
[443.400-444.750] you know, it kind of like does stuff on
[444.760-446.070] your behalf even if you're not looking
[446.080-447.190] kind of thing.
[447.200-449.190] Um and then also has like maybe more
[449.200-450.750] sophisticated memory systems etc. that
[450.760-452.990] are not yet implemented in agents. So
[453.000-454.110] um Open Claude has a lot more
[454.120-455.350] sophisticated memory I would say than
[455.360-457.110] what you would get by default uh which
[457.120-458.550] is just a memory compaction when your
[458.560-460.110] context runs out, right? You think
[460.120-461.990] that's the piece that resonated for more
[462.000-464.350] users versus like perhaps like broader
[464.360-466.870] tool access? For Open Claude? Yeah. Uh
[466.880-468.110] there's like I think there's at least
[468.120-469.150] five things that are really good ideas
[469.160-470.990] in here. Yeah, good job, Peter. I mean
[471.000-473.270] Peter has done a really amazing job. Um
[473.280-475.910] I saw him recently. Uh and I talked to
[475.920-477.590] him about it and I he's very humble
[477.600-491.590] about it. But I think he
[492.790-492.800] innovated simultaneously in like five
[492.800-494.590] different ways and put it all together.
[494.600-496.150] Um so for example like the soul and D
[496.160-497.950] document. Like he actually really
[497.960-499.350] crafted a personality that is kind of
[499.360-500.670] compelling and interesting. And I feel
[500.680-501.710] like a lot of the current agents they
[501.720-503.150] don't get this correctly. I actually
[503.160-504.150] think a Claude has a pretty good
[504.160-506.270] personality. It feels like a teammate
[506.280-508.990] uh and it's excited with you etc.
[509.000-510.870] I would say um for example Codex is a
[510.880-513.149] lot more dry um which is kind of
[513.159-514.230] interesting because [laughter] in it's
[514.240-516.469] true. You know, it doesn't it
[516.479-517.909] and the other thing I would say is for
[517.919-519.270] example with Claude I think they dialed
[519.280-521.310] the sycophancy fairly well where when
[521.320-522.990] Claude gives me praise, I do feel like I
[523.000-524.830] slightly deserve it because sometimes I
[524.840-525.990] kind of give it like not very well
[526.000-528.310] formed thoughts and uh I give it an idea
[528.320-529.670] that I don't think it's fully baked and
[529.680-530.990] it doesn't actually react very strongly.
[531.000-532.390] It's like, oh yeah, we can implement
[532.400-534.350] that. But when it's a really good idea
[534.360-536.630] by my own account, it does uh seem to
[536.640-538.270] reward it a bit more. And so I kind of
[538.280-539.830] feel like I'm trying to like earn its
[539.840-541.750] praise which is really weird. And so I
[541.760-543.470] do think the personality matters a lot
[543.480-545.070] uh and I think a lot of the other uh
[545.080-546.630] tools maybe don't appreciate it as much.
[546.640-548.070] And I think in this aspect also Peter
[548.080-549.550] really cares about this and so that was
[549.560-551.350] correct. And then the memory system and
[551.360-553.470] then uh just, you know, he's just having
[553.480-555.750] fun with this um and then the the single
[555.760-556.910] WhatsApp portal to all of the
[556.920-557.550] automation.
[557.560-559.950] &gt;&gt; Yeah. Is there something that you have
[559.960-563.310] done personally with your claws beyond
[563.320-564.710] software engineering that you think is
[564.720-566.430] fun or interesting? Yeah, so in January
[566.440-568.270] I had a claw I went through a period of
[568.280-570.710] claw psychosis. So I built um I have a
[570.720-572.510] claw basically that takes care of my
[572.520-574.750] home and I call him Dobby the elf uh
[574.760-575.750] claw.
[575.760-579.350] Um and uh basically I used uh the agents
[579.360-581.990] to find all of the smart home subsystems
[582.000-584.070] of my home on the local area network
[584.080-585.070] which I was kind of surprised that it
[585.080-586.350] worked out of the box. Like I just told
[586.360-587.750] it that I think I have Sonos at home.
[587.760-589.470] Like can you try to find it? And it goes
[589.480-592.030] and it did like IP scan of all of the um
[592.040-594.150] basically um computers on the local area
[594.160-596.190] network and and found the Sonos thing uh
[596.200-599.230] the Sonos uh, system and it turned out
[599.240-600.550] that there's no password protection or
[600.560-601.550] anything like that. It just logged in
[601.560-602.390] and it's like, "Oh, yeah, you have these
[602.400-604.550] Sonos systems installed. I Let me try to
[604.560-606.310] reverse engineer how it's working." It
[606.320-607.790] does some web searches and it finds
[607.800-608.710] like, "Okay, these are the API
[608.720-610.510] endpoints." And then it's like, "Do you
[610.520-611.710] want to try it?" And I'm like, "Whoa,
[611.720-612.630] like you just did that." And I'm like,
[612.640-613.910] "Yeah, can you try to play something in
[613.920-616.110] the study?" And, uh, it does and music
[616.120-617.670] comes out and I'm like, "I can't believe
[617.680-619.270] I just That's crazy. That's like three
[619.280-619.950] prompts. Yeah.
[619.960-620.950] &gt;&gt; I can't believe I just typed in like,
[620.960-622.070] "Can you find my Sonos?" and then
[622.080-623.670] suddenly it's playing music. And it did
[623.680-626.070] the same for lights. And so like it kind
[626.080-627.150] of hacked in, figured out the whole
[627.160-629.070] thing, uh, created APIs, created
[629.080-631.030] dashboard so I could see the command,
[631.040-632.270] uh, kind of center of like all of my
[632.280-633.790] lights in the home. And then it was like
[633.800-635.390] switching lights on and off and, you
[635.400-637.550] know, so I can ask it like, "Dobby, it's
[637.560-639.350] sleepy time." And when it's sleepy time
[639.360-640.710] that just means all the lights go off,
[640.720-642.910] etc. and like so on. So it controls all
[642.920-645.550] of my lights, my HVAC, my shades, uh,
[645.560-647.670] the pool and, uh, the spa and also my
[647.680-649.270] security system. So I have a camera
[649.280-651.350] pointed outside of the house and anytime
[651.360-654.230] someone rolls in I have a Quinn, uh,
[654.240-655.710] a Quinn, uh, model that looks at the
[655.720-657.470] videos. So first of all there's change
[657.480-658.550] detection. Right.
[658.560-659.590] &gt;&gt; And then based on change detection it
[659.600-661.350] goes to Quinn and then it actually like
[661.360-663.550] tells me, um, it sends me a text to my
[663.560-665.510] WhatsApp. It shows an image from the
[665.520-667.950] outside and it says, "Hey, a FedEx truck
[667.960-669.870] just pulled up. FedEx truck just pulled
[669.880-671.310] up and you might want to check it and
[671.320-672.350] you got new mail or something like
[672.360-674.350] that." And Dobby just text me this. This
[674.360-677.829] is really incredible. Um, so so Dobby is
[677.839-679.510] in charge of the house. I text through
[679.520-681.550] with it through WhatsApp, um,
[681.560-683.070] and it's been like really fun to have
[683.080-684.870] these macro actions that maintain my
[684.880-686.590] house. I haven't like really pushed it,
[686.600-687.990] uh, like way more beyond that and I
[688.000-689.230] think people are doing a lot more crazy
[689.240-690.910] things with it, uh, but for me even just
[690.920-692.390] the home automation setup I used to use
[692.400-694.190] like six apps, uh, completely different
[694.200-695.350] apps and I don't have to use these apps
[695.360-696.910] anymore. Like Dobby controls everything
[696.920-699.510] in natural language. It's amazing. Um,
[699.520-700.750] and so I think like I haven't even
[700.760-702.790] pushed the paradigm fully but already
[702.800-704.710] that is so helpful and so inspiring I
[704.720-705.870] would say. Do you think that's
[705.880-707.510] indicative of like what people want from
[707.520-709.070] a user experience perspective with
[709.080-710.710] software, right? Because I I don't
[710.720-712.670] think, you know, it's pretty ignored
[712.680-714.430] that it takes humans effort to like
[714.440-717.670] learn new software, like new UI. Yeah. I
[717.680-719.910] think, uh, to some extent that's right.
[719.920-721.110] It's like working backwards from how
[721.120-724.150] people think an AI should be because
[724.160-725.710] what people have in their mind of like
[725.720-727.070] what an AI is is not actually what an
[727.080-729.710] LLM is by by like in the raw sense. Like
[729.720-731.150] LLM is a token generator, you know, like
[731.160-732.590] more tokens come out. But what they
[732.600-733.910] think of is like this
[733.920-736.310] this persona identity that they can tell
[736.320-738.510] stuff and it remembers it, you know?
[738.520-739.870] And, uh, it's just kind of an entity
[739.880-740.990] behind the WhatsApp. It's like a lot
[741.000-743.750] more understandable. Mhm. Uh, so I think
[743.760-744.990] to some extent it's like matching the
[745.000-746.390] expectations that humans already have
[746.400-747.790] for what an AI should behave but under
[747.800-748.990] the hood it's like a lot of technical
[749.000-750.750] details go into that. And LLMs are too
[750.760-754.070] raw of a primitive, uh, to actually, um,
[754.080-756.310] type check as AI I think for most people
[756.320-758.110] if that makes sense. Yeah. Um, I think
[758.120-759.790] that's like how we understand what the
[759.800-763.310] AI is and like the, um, description of
[763.320-766.270] it as Dobby or some persona obviously
[766.280-768.510] resonates with people. Um, I also think
[768.520-770.030] that it it
[770.040-772.190] uh, the unification that you did across
[772.200-773.670] your six different software systems for
[773.680-775.390] your home automation speaks to a
[775.400-776.910] different question of like
[776.920-777.910] do people really want all of the
[777.920-779.630] software that we have today? Yeah.
[779.640-781.550] Right? Um, because I I would argue like,
[781.560-783.630] well, you have the hardware but you've
[783.640-786.470] now thrown away the software or the UX
[786.480-788.750] layer of it. Um, do you think that's
[788.760-790.390] what people want? Yeah, I think there's
[790.400-791.550] this like
[791.560-792.910] there's this sense that these apps that
[792.920-794.550] are on the app store for using these
[794.560-796.550] smart home devices, etc. Uh, these
[796.560-797.829] shouldn't even exist kind of in a
[797.839-799.230] certain sense. Like shouldn't it just be
[799.240-801.590] APIs and shouldn't agents be just using
[801.600-805.630] it directly? And, um, wouldn't it like I
[805.640-806.790] can do all kinds of home automation
[806.800-808.670] stuff that, uh, in any individual app
[808.680-810.430] will not be able to do, right? Um, and
[810.440-811.990] an LLM can actually drive the tools and
[812.000-813.590] call all the right tools and do uh, do
[813.600-815.910] pretty complicated things. Um,
[815.920-818.230] and so in a certain sense it does point
[818.240-819.710] to this like maybe there's like an
[819.720-821.470] overproduction of lots of custom bespoke
[821.480-823.550] apps that shouldn't exist because agents
[823.560-825.670] kind of like crumble them up and
[825.680-826.829] everything should be a lot more just
[826.839-829.070] like exposed API endpoints and agents
[829.080-831.230] are the glue of the intelligence that
[831.240-833.070] actually like tool calls all the all the
[833.080-835.350] parts. Um, another example is like my
[835.360-836.910] treadmill. Uh, there's an app for my
[836.920-838.510] treadmill and I wanted to like keep
[838.520-840.470] track of how often I do my cardio, uh,
[840.480-842.150] but like I don't want to like log into
[842.160-844.630] web UI and go through a flow and etc.
[844.640-846.030] Like all this should just be like make
[846.040-848.110] APIs available and this is kind of, you
[848.120-850.510] know, going towards the agentic, um,
[850.520-852.310] sort of web or like agent first, uh,
[852.320-853.829] tools and all this kind of stuff. So I
[853.839-855.069] think the industry just has to
[855.079-856.710] reconfigure in so many ways that's like
[856.720-858.030] the customer is not the human anymore.
[858.040-859.630] It's like agents who are acting on
[859.640-861.430] behalf of humans and this refactoring
[861.440-863.390] will be will probably be substantial in
[863.400-865.110] a certain sense. One way that people
[865.120-866.870] sometimes push back on this is like, do
[866.880-868.350] people Do you Do we expect people to
[868.360-870.230] write code some of these tools? Do we
[870.240-872.150] expect normal people to do this kind of
[872.160-873.910] stuff that I described? Mhm. But I think
[873.920-875.230] to some extent
[875.240-876.470] this is just, you know, technology as it
[876.480-878.190] exists today and right now there is some
[878.200-879.750] write coding and I'm actually watching
[879.760-882.150] it and I'm working with the system but I
[882.160-883.350] kind of feel like this kind of stuff
[883.360-885.150] that I just talked about this should be
[885.160-887.510] free like in a year or two or three.
[887.520-888.790] There's no write coding involved. This
[888.800-890.390] is trivial. This is table stakes. This
[890.400-892.350] is like any AI, even the open source
[892.360-894.110] models, etc. can like do this. You
[894.120-896.190] should be able to translate it from a
[896.200-899.069] less technical humans intent very easily
[899.079-900.110] to this outcome.
[900.120-901.510] &gt;&gt; Yeah. Today it's write coding and it's
[901.520-902.470] involved and not many people are going
[902.480-902.910] to do it but
[902.920-903.949] &gt;&gt; And you still have to make some design
[903.959-905.230] decisions, right? We were talking about
[905.240-907.910] like we take frames for example. Yeah.
[907.920-910.150] Yeah. But I kind of feel like this will
[910.160-912.430] just, uh, start to the barrier will just
[912.440-914.230] come down and it's just ephemeral
[914.240-917.069] software on your behalf and some kind of
[917.079-918.910] like claw is handling all the details
[918.920-920.510] for you but you're not involved. Claw
[920.520-922.390] has a Claw has a machine and it will
[922.400-923.710] figure it out and it's just presenting
[923.720-925.630] you UIs and you're like saying stuff,
[925.640-926.949] you know? Mhm.
[926.959-929.470] Why haven't you, um, I guess like pushed
[929.480-930.550] the boundaries of what you can do
[930.560-932.590] personally with claws? Like is it, you
[932.600-935.150] know, you're focusing on more important
[935.160-938.270] projects, auto research, etc. or, uh,
[938.280-940.430] you're climbing the hill to mastery or
[940.440-942.069] something else, right? Yeah, I just feel
[942.079-943.630] like I'm so distracted by everything so
[943.640-945.390] I spend I [laughter] spend like a week
[945.400-947.590] on the claw stuff and I I have more to
[947.600-949.350] do almost, um,
[949.360-950.270] but I will say that, um,
[950.280-951.430] &gt;&gt; It's like Jensen told us we're all just
[951.440-953.710] busier, unfortunately.
[953.720-955.030] &gt;&gt; Uh, I didn't really take advantage of a
[955.040-957.230] lot of like email and calendar and all
[957.240-958.270] this other stuff and I didn't really
[958.280-959.910] have access cuz I'm still a little bit
[959.920-961.430] like suspicious and it's still very new
[961.440-963.150] and rough around the edges. So I didn't
[963.160-964.350] want to give it like full access to my
[964.360-966.069] digital life yet and part of it is just
[966.079-968.470] the security, privacy and uh, just being
[968.480-971.150] very cautious in that in that realm.
[971.160-973.110] And, um, so some of it is like held back
[973.120-974.470] by that I would say. Yeah, maybe that's
[974.480-976.550] like the dominant dominant feature but
[976.560-977.750] some of it is also just I feel so
[977.760-979.230] distracted because I feel like I had a
[979.240-980.870] week of claw and then other stuff is
[980.880-983.350] happening and What was the, um, I mean
[983.360-986.110] you've talked about like being able to
[986.120-988.790] train or at least optimize a uh, a a
[988.800-990.670] model as a task you want to see agents
[990.680-992.150] do for a long time. Like what was the
[992.160-994.030] motivation behind auto research? Auto
[994.040-996.150] research, yeah. So I think like
[996.160-997.790] I had a tweet earlier where I kind of
[997.800-1000.110] like said something along the lines of
[1000.120-1001.510] to get the most out of the tools that
[1001.520-1003.190] have become available now you have to
[1003.200-1004.430] remove yourself as the as the
[1004.440-1006.470] bottleneck. You can't be there to prompt
[1006.480-1008.069] the next thing. You're You need to take
[1008.079-1010.270] yourself outside. Um, you have to
[1010.280-1011.470] arrange things such that they're
[1011.480-1013.550] completely autonomous. And the more you
[1013.560-1014.550] you know, how can you maximize your
[1014.560-1016.110] token throughput and not be in the loop?
[1016.120-1018.550] This is the this is the goal. And so
[1018.560-1019.790] I kind of mentioned that the the name of
[1019.800-1020.750] the game now is to increase your
[1020.760-1022.870] leverage. Uh, I put in just very few
[1022.880-1024.510] tokens just once in a while and a huge
[1024.520-1026.550] amount of stuff happens on my behalf.
[1026.560-1028.270] And so auto research like I tweeted that
[1028.280-1029.790] and I think people liked it and whatnot
[1029.800-1030.949] but it
[1030.959-1032.189] they haven't like maybe worked through
[1032.199-1033.750] like the implications of that and for me
[1033.760-1034.829] auto research is an example of like an
[1034.839-1036.910] implication of that. Where it's like I
[1036.920-1038.350] don't want to be like the researcher in
[1038.360-1040.590] loop like looking at results, etc. Like
[1040.600-1043.150] I'm I'm holding the system back. So the
[1043.160-1044.829] question is how do I refactor all the
[1044.839-1046.710] abstractions so that I'm not I have to
[1046.720-1048.669] arrange it once and hit go. The name of
[1048.679-1050.750] the game is how can you get more agents
[1050.760-1051.990] running for longer periods of time
[1052.000-1053.350] without your involvement doing stuff on
[1053.360-1055.470] your behalf? And auto research is just,
[1055.480-1056.870] yeah, here's an objective, here's a
[1056.880-1058.390] metric, here's your boundaries of what
[1058.400-1059.790] you can and cannot do.
[1059.800-1061.030] And go.
[1061.040-1063.350] And, uh, yeah, it worked.
[1063.360-1065.270] &gt;&gt; at its effectiveness. Yeah, I I didn't
[1065.280-1067.190] expect, uh, it to work because so I have
[1067.200-1069.590] the project data chat, um,
[1069.600-1070.710] and fundamentally like I think a lot of
[1070.720-1072.030] people are very confused with my
[1072.040-1073.830] obsession for like training GPT-2 models
[1073.840-1075.910] and so on. But for me, uh, training GPT
[1075.920-1077.110] models and so on is just a little
[1077.120-1078.270] harness, a little playground for
[1078.280-1079.990] training LLMs. And fundamentally what
[1080.000-1081.470] I'm more interested in is like this idea
[1081.480-1082.710] of recursive self-improvement and to
[1082.720-1084.190] what extent you can actually have LLMs
[1084.200-1085.990] improving LLMs because I think all the
[1086.000-1088.030] frontier labs this is like the thing
[1088.040-1090.430] Mhm. uh, for obvious reasons and they're
[1090.440-1092.030] all trying to recursively self-improve
[1092.040-1093.590] roughly speaking. And so for me this is
[1093.600-1095.630] kind of like, um, a little playpen of
[1095.640-1098.550] that. Um, and I guess I like tuned Nan
[1098.560-1100.190] Chat already quite a bit by hand in the
[1100.200-1101.310] good old fashion way that I'm used to.
[1101.320-1102.350] Like I'm a researcher. I've done this
[1102.360-1103.550] for like, you know, two decades. I have
[1103.560-1105.030] some amount of like What is the opposite
[1105.040-1108.070] of hubris? Uh, yeah. [laughter]
[1108.080-1110.750] Earned confidence? Okay. I have like two
[1110.760-1112.190] decades of like, "Oh, I've trained this
[1112.200-1113.710] model like thousands of times. I've
[1113.720-1114.550] like,
[1114.560-1116.070] um, so I've done a bunch of experiments.
[1116.080-1117.350] I've done hyperparameter tuning. I've
[1117.360-1118.590] done all the things I'm very used to and
[1118.600-1119.909] I've done for two decades. Yeah. And
[1119.919-1121.909] I've gotten to a certain point and I
[1121.919-1123.630] thought it was like fairly well tuned
[1123.640-1125.390] and then I let auto research go for like
[1125.400-1127.470] overnight and it came back with like
[1127.480-1128.990] tunings that I didn't see. Mhm. And
[1129.000-1130.550] yeah, I did forget like the weight decay
[1130.560-1132.110] on the value embeddings and my Adam
[1132.120-1134.510] betas were not sufficiently tuned and
[1134.520-1136.070] these things just jointly interact. So
[1136.080-1137.350] like once you tune one thing the other
[1137.360-1138.870] things have to potentially change too.
[1138.880-1140.030] You know, I shouldn't be a bottleneck. I
[1140.040-1140.750] shouldn't be running these
[1140.760-1142.070] hyperparameter optimizations. I
[1142.080-1143.669] shouldn't be looking at the results.
[1143.679-1145.390] There's objective criteria in this case.
[1145.400-1146.830] Uh, so you just let you just have to
[1146.840-1147.990] arrange it so that it can just go
[1148.000-1149.750] forever. So that's a single sort of
[1149.760-1151.030] version of auto research of like a
[1151.040-1153.230] single loop trying to improve. And I was
[1153.240-1155.310] surprised that it, um, it found these
[1155.320-1156.350] things that I
[1156.360-1157.510] you know, the repo was already fairly
[1157.520-1159.110] well tuned and still found something.
[1159.120-1160.510] And that's just a single it's a single
[1160.520-1162.870] loop. Like these frontier labs they have
[1162.880-1165.149] GPU clusters of tens of thousands of
[1165.159-1166.149] them.
[1166.159-1167.669] And so it's very easy to imagine how you
[1167.679-1169.710] would basically get a lot of this
[1169.720-1172.230] automation on, um, smaller models. And
[1172.240-1173.590] fundamentally everything around like
[1173.600-1174.990] frontier level intelligence is about
[1175.000-1177.310] extrapolation and scaling loss. And so
[1177.320-1178.110] you basically do a ton of the
[1178.120-1180.190] exploration on the smaller models and
[1180.200-1182.990] then you try to, um, extrapolate out. So
[1183.000-1184.350] you're saying our research efforts are
[1184.360-1185.950] going to get more efficient. Like we're
[1185.960-1187.070] going to have better direction for when
[1187.080-1188.950] we scale as well if we can do this
[1188.960-1190.030] experimentation better.
[1190.040-1191.669] &gt;&gt; Yeah, I would say that like the most
[1191.679-1192.830] interesting project and probably what
[1192.840-1194.590] the frontier labs are working on is uh,
[1194.600-1195.870] Mhm. Yeah. you know, you experiment on
[1195.880-1197.270] the smaller models. You try to make it
[1197.280-1198.870] as autonomous as possible. Remove
[1198.880-1199.963] researchers
[1199.973-1200.150] &gt;&gt; [laughter]
[1200.160-1202.230] &gt;&gt; from the loop. They have way too much
[1202.240-1204.390] What is the What is the opposite
[1204.400-1205.910] of too much confidence? Yeah, yeah, they
[1205.920-1207.150] don't know. They shouldn't be touching
[1207.160-1208.550] any of this really. And so you have to
[1208.560-1209.750] like rewrite the whole thing because
[1209.760-1211.310] right now, I mean certainly they can
[1211.320-1213.670] contribute ideas. But okay, they
[1213.680-1214.990] shouldn't actually be enacting these
[1215.000-1217.350] ideas. There is a queue of ideas and
[1217.360-1218.670] there's maybe an automated scientist
[1218.680-1220.310] that comes up with ideas based on all
[1220.320-1221.950] the archive papers and GitHub repos and
[1221.960-1224.150] it funnels ideas in or researchers can
[1224.160-1225.670] contribute ideas, but it's a single
[1225.680-1227.830] queue and there is workers that pull
[1227.840-1230.070] items and they try them out. And
[1230.080-1231.910] whatever works just gets sort of put on
[1231.920-1233.990] the feature branch and maybe some people
[1234.000-1235.230] like
[1235.240-1237.190] monitor the feature branch and merge to
[1237.200-1239.710] the main branch sometimes. So
[1239.720-1242.070] yeah, just removing humans from all the
[1242.080-1243.430] processes and automating as much as
[1243.440-1245.070] possible and getting high token tokens
[1245.080-1246.630] per second throughputs and it does
[1246.640-1247.990] require rethinking of all the
[1248.000-1249.670] abstractions
[1249.680-1252.870] and everything has to be reshuffled. So
[1252.880-1254.190] yeah, I think it's very exciting. If we
[1254.200-1257.510] take one more recursive step here,
[1257.520-1258.630] when is the model going to write a
[1258.640-1260.750] better program MD than you?
[1260.760-1261.950] Yeah.
[1261.960-1263.590] Also program MD is like
[1263.600-1265.030] &gt;&gt; loop. Yeah, exactly.
[1265.040-1267.910] &gt;&gt; Yeah. So program MD is my crappy attempt
[1267.920-1270.070] at describing like how the auto
[1270.080-1271.830] researcher should work. Like oh, do this
[1271.840-1273.670] then do that and that and then try these
[1273.680-1275.190] kinds of ideas and then here's maybe
[1275.200-1276.590] some ideas like look at architecture,
[1276.600-1278.390] look at optimizer, etc. But I just came
[1278.400-1279.950] up with with this in markdown, right?
[1279.960-1281.110] &gt;&gt; Mhm.
[1281.120-1283.030] And so
[1283.040-1284.510] yeah, exactly.
[1284.520-1286.070] You want some kind of an auto research
[1286.080-1288.430] loop maybe that looks for
[1288.440-1289.710] You can imagine that different program
[1289.720-1291.910] that MDs would
[1291.920-1294.630] would give you different progress. So
[1294.640-1295.790] you basically every research
[1295.800-1298.350] organization is described by program MD.
[1298.360-1300.230] A research organization is a set of
[1300.240-1301.630] markdown files that describe all the
[1301.640-1303.550] roles and how the whole thing connects.
[1303.560-1305.510] And you can imagine having a better
[1305.520-1307.070] research organization. So maybe they do
[1307.080-1308.510] fewer stand-ups in the morning because
[1308.520-1310.030] they're useless. And this is all just
[1310.040-1311.470] code, right?
[1311.480-1312.990] And so you can So one organization can
[1313.000-1314.470] have fewer stand-ups, one organization
[1314.480-1316.070] can have more.
[1316.080-1317.270] One organization can be very
[1317.280-1319.150] risk-taking, one organization can be
[1319.160-1320.950] less. As you can definitely imagine that
[1320.960-1322.950] you have multiple research orgs
[1322.960-1324.590] and then they all have code. And once
[1324.600-1325.630] you have code, then you can imagine
[1325.640-1327.390] tuning the code. So 100% there's like
[1327.400-1329.710] the metal layer of it. Uh
[1329.720-1331.110] Did you see my text about my contest
[1331.120-1334.430] idea? My contest idea was
[1334.440-1335.350] like
[1335.360-1338.270] let people write different program MDs,
[1338.280-1340.550] right? And and so for same hardware,
[1340.560-1342.230] where do you get most improvement?
[1342.240-1343.350] &gt;&gt; Oh, I see. And then you can take all
[1343.360-1345.510] that data and then give it to the model
[1345.520-1346.750] and say write a better program MD.
[1346.760-1348.030] &gt;&gt; Yes, yes.
[1348.040-1348.630] Yeah, exactly.
[1348.640-1349.510] &gt;&gt; We're going to get something better.
[1349.520-1350.590] Like there's no way we don't, right?
[1350.600-1352.310] &gt;&gt; 100% look at
[1352.320-1354.030] where the improvements came from and
[1354.040-1356.110] like can I change the program MD such
[1356.120-1357.669] that more of these kinds of things would
[1357.679-1360.070] be done or like things that didn't work
[1360.080-1361.550] except
[1361.560-1363.270] you can 100% imagine doing that. So I
[1363.280-1365.070] think this is a great idea, but it's
[1365.080-1365.950] like
[1365.960-1367.150] you know, I think like you can sort of
[1367.160-1368.630] go one step at a time where you sort of
[1368.640-1370.630] have one process and then second process
[1370.640-1371.750] and then the next process and these are
[1371.760-1373.270] all layers of an onion.
[1373.280-1375.310] Like the LLM sort of part is now taken
[1375.320-1377.030] for granted. The agent part is now taken
[1377.040-1378.990] for granted. Now the claw-like entities
[1379.000-1380.390] are taken for granted and now you can
[1380.400-1381.750] have multiple of them and now you can
[1381.760-1383.030] have instructions to them and now you
[1383.040-1384.270] can have optimization over the
[1384.280-1386.030] instructions and it's just like a little
[1386.040-1387.870] too much, you know, but I mean this is
[1387.880-1389.150] why it gets to the psychosis is that
[1389.160-1390.590] this is like infinite and everything is
[1390.600-1392.710] scale issue and that's why I feel like
[1392.720-1394.550] Yeah, that's just coming back to This is
[1394.560-1396.466] why it's so insane. Okay, well, if
[1396.476-1397.310] [laughter] we're we're just trying to
[1397.320-1400.870] like diagnose the current moment and
[1400.880-1402.950] what is a relevant skill right now, what
[1402.960-1404.230] do you like what do you think is the
[1404.240-1406.270] implication that this
[1406.280-1407.350] that this is the loop we should be
[1407.360-1409.390] trying to achieve in different areas and
[1409.400-1411.350] then it works, right? Like you know,
[1411.360-1412.550] remove
[1412.560-1414.550] create the metric or create the ability
[1414.560-1416.870] for agents to continue working on it
[1416.880-1418.390] without you. Do we still have
[1418.400-1420.510] performance engineering? Like what
[1420.520-1422.070] Yeah, I mean so there's a few caveats
[1422.080-1423.510] that I would put on top of the LLM
[1423.520-1425.150] psychosis. So number one,
[1425.160-1426.550] this is extremely well suited to
[1426.560-1428.270] anything that has objective metrics that
[1428.280-1429.870] are easy to evaluate. So for example,
[1429.880-1431.390] like writing kernels for more efficient
[1431.400-1432.430] CUDA,
[1432.440-1434.350] you know, code for various parts of the
[1434.360-1436.710] model, etc. are a perfect fit because
[1436.720-1438.390] you have inefficient code and then you
[1438.400-1439.830] want efficient code that has the exact
[1439.840-1442.110] same behavior but it's much faster.
[1442.120-1444.590] Perfect fit. So a lot of things like
[1444.600-1446.510] like are perfect fit for auto research,
[1446.520-1448.550] but many things will not be. And so they
[1448.560-1449.830] it's just if you can't evaluate then you
[1449.840-1452.190] can't auto research it, right?
[1452.200-1453.630] So that's like caveat number one. And
[1453.640-1454.990] then maybe caveat number two I would say
[1455.000-1456.470] is you know, we're we're kind of talking
[1456.480-1457.750] about the next steps and we kind of see
[1457.760-1458.750] what the next steps are, but
[1458.760-1460.470] fundamentally the the whole thing still
[1460.480-1462.230] doesn't it still kind of like bursting
[1462.240-1463.150] at the seams a little bit and there's
[1463.160-1465.550] cracks and it doesn't fully work and if
[1465.560-1467.230] you kind of try to go too far ahead, the
[1467.240-1469.310] whole thing is actually net not useful
[1469.320-1471.070] if that makes sense.
[1471.080-1472.750] Because these models like still are not,
[1472.760-1474.070] you know, they've improved a lot, but
[1474.080-1475.750] they're still are like rough around the
[1475.760-1477.270] edges is maybe the way I would describe
[1477.280-1479.350] it. I simultaneously feel like I'm
[1479.360-1481.390] talking to an extremely brilliant PhD
[1481.400-1483.150] student who's been like a systems
[1483.160-1484.950] programmer for their entire life and a
[1484.960-1487.310] 10-year-old. And it's so weird because
[1487.320-1489.070] humans like there's like I feel like
[1489.080-1490.630] they're a lot more coupled like you have
[1490.640-1492.830] to you know, um Yes, you wouldn't you
[1492.840-1494.510] wouldn't encounter that combination.
[1494.520-1496.430] &gt;&gt; This jaggedness is really strange and
[1496.440-1497.750] humans have a lot less of that kind of
[1497.760-1499.030] jaggedness, although they definitely
[1499.040-1499.957] have some.
[1499.967-1500.470] &gt;&gt; [laughter]
[1500.480-1502.870] &gt;&gt; But humans have a lot more jaggedness.
[1502.880-1504.070] Uh sorry, the agents have a lot more
[1504.080-1505.710] jaggedness where
[1505.720-1507.310] sometimes like
[1507.320-1508.630] you know, I ask for functionality and it
[1508.640-1509.790] like comes back with something that's
[1509.800-1511.669] just like totally wrong and then we get
[1511.679-1512.870] into loops that are totally wrong and
[1512.880-1514.270] then I'm just I get so frustrated with
[1514.280-1516.030] the agents all the time still because
[1516.040-1517.830] you feel the power of it,
[1517.840-1520.710] but you also there's still like
[1520.720-1521.910] it does not say statistical things once
[1521.920-1523.950] in a while for me as well. I get very
[1523.960-1526.390] annoyed [clears throat] when
[1526.400-1529.350] I feel like the agent wasted a lot of
[1529.360-1530.870] compute on something it should have
[1530.880-1533.590] recognized was an obvious problem. Yeah.
[1533.600-1534.669] I think like some of the bigger things
[1534.679-1536.750] is like maybe what's under underneath it
[1536.760-1539.030] if I could hypothesize is fundamentally
[1539.040-1539.910] these models are trained via
[1539.920-1540.990] reinforcement learning. So they're
[1541.000-1541.990] actually struggling with the exact same
[1542.000-1543.630] thing we just talked about which is the
[1543.640-1545.750] labs can improve the models in anything
[1545.760-1547.117] that is verifiable or that
[1547.127-1548.790] [clears throat] has rewards. So did you
[1548.800-1550.750] write the program correctly and does it
[1550.760-1552.550] you do you the unit tests check out? Yes
[1552.560-1554.110] or no. But some of the things where
[1554.120-1555.310] they're struggling is like for example,
[1555.320-1557.350] I think they have a tough time with like
[1557.360-1559.150] nuance of maybe what I what I had in
[1559.160-1560.910] mind or what I intended and when to ask
[1560.920-1562.630] clarifying questions.
[1562.640-1563.230] Um
[1563.240-1565.430] or like what I Yeah, it's just um
[1565.440-1567.070] anything that feels softer is like
[1567.080-1569.390] worse. And so you're kind of like you're
[1569.400-1571.070] either on rails and you're part of the
[1571.080-1572.910] super intelligence circuits or you're
[1572.920-1574.430] not on rails and you're outside of the
[1574.440-1575.630] verifiable domains and suddenly
[1575.640-1577.710] everything kind of just like meanders.
[1577.720-1579.150] Like maybe another way to put it is if
[1579.160-1581.310] you go to if today if you go to like
[1581.320-1582.830] state-of-the-art model, ChatGPT and you
[1582.840-1585.710] ask it tell me a joke, um
[1585.720-1586.550] do you know what joke you're going to
[1586.560-1589.230] get? There's the joke. The joke? I do
[1589.240-1591.310] feel I I I can't tell you like the you
[1591.320-1592.669] know, standard form of it, but I do feel
[1592.679-1594.190] like ChatGPT has like three jokes.
[1594.200-1596.190] &gt;&gt; Yeah, yeah. So the the joke that
[1596.200-1597.630] apparently all the LLMs like love the
[1597.640-1600.590] most is why do scientists not trust
[1600.600-1602.430] atoms? Okay. Because they make
[1602.440-1603.990] everything up. Okay.
[1604.000-1605.710] &gt;&gt; They make everything up.
[1605.720-1606.830] So this is still
[1606.840-1608.750] &gt;&gt; emerge? So this is the joke you would
[1608.760-1610.350] get like three or four years ago and
[1610.360-1611.830] this is the joke you still get today.
[1611.840-1612.390] Okay.
[1612.400-1613.910] &gt;&gt; So even though the models have improved
[1613.920-1616.030] tremendously and if you give them an
[1616.040-1618.270] agentic task, they will just go for
[1618.280-1620.910] hours and move mountains for you. And
[1620.920-1622.590] then you ask for like a joke and it has
[1622.600-1624.230] a stupid joke. It's crappy joke from
[1624.240-1626.070] five years ago and it's because it's
[1626.080-1628.830] outside of the it's outside of the RL.
[1628.840-1629.710] It's outside of the reinforcement
[1629.720-1630.710] learning. It's outside of what's being
[1630.720-1632.990] improved. It's like and it's part of the
[1633.000-1635.070] jaggedness of like shouldn't you expect
[1635.080-1636.510] models as they get better to also have
[1636.520-1638.070] like better jokes or more diversity of
[1638.080-1640.190] them or it's just it's not being
[1640.200-1643.910] optimized and stuck. Do you
[1643.920-1646.669] think that that implies that we are not
[1646.679-1649.230] seeing like generalization in the sense
[1649.240-1651.830] of like broader intelligence of joke
[1651.840-1654.150] smartness being attached to code
[1654.160-1655.830] smartness? Yeah, I think there's some
[1655.840-1657.910] decoupling where some things are
[1657.920-1659.390] verifiable and some things are not and
[1659.400-1660.390] some things are optimized for
[1660.400-1661.870] arbitrarily by the labs depending on
[1661.880-1663.510] like what data went in and some things
[1663.520-1665.870] are not and um
[1665.880-1666.350] and
[1666.360-1668.830] &gt;&gt; But I mean the the premise there's a you
[1668.840-1670.990] know, premise from some research groups
[1671.000-1673.150] that if you're smarter at code
[1673.160-1675.510] generation or in these verifiable
[1675.520-1676.350] fields, you should be better at
[1676.360-1678.470] everything. And like the
[1678.480-1679.990] the joke situation suggests that that's
[1680.000-1681.310] not happening at all.
[1681.320-1681.710] Okay.
[1681.720-1682.870] &gt;&gt; Yeah, I don't think that's happening. I
[1682.880-1683.830] think
[1683.840-1684.910] I think maybe we're seeing like a little
[1684.920-1686.270] bit of that, but not like a satisfying
[1686.280-1686.750] amount.
[1686.760-1689.630] &gt;&gt; Yeah, that jaggedness exists in humans.
[1689.640-1691.150] You [laughter] can be very very good at
[1691.160-1692.430] math
[1692.440-1693.910] and still tell really bad jokes.
[1693.920-1695.390] &gt;&gt; Yeah, that's true. Yeah, but it just it
[1695.400-1697.070] still means that we're not getting like
[1697.080-1698.669] the story is that we're getting a lot of
[1698.679-1700.110] the intelligence and capabilities in all
[1700.120-1702.750] the domains of society like for free as
[1702.760-1704.190] we get better and better models and
[1704.200-1705.590] that's not like exactly fundamentally
[1705.600-1707.190] what's going on and there's some blind
[1707.200-1708.510] spots and some things are not being
[1708.520-1710.710] optimized for and this is all clustered
[1710.720-1712.870] up in these neural net opaque models,
[1712.880-1715.230] right? So you're either on rails of what
[1715.240-1716.430] it was trained for and everything is
[1716.440-1717.669] like you're going at speed of light or
[1717.679-1719.149] you're not.
[1719.159-1721.750] And so it's the jaggedness. So
[1721.760-1722.470] um
[1722.480-1723.870] So that's why I think like even though
[1723.880-1725.950] the the progression is obvious what
[1725.960-1728.990] should happen, you can't let it fully go
[1729.000-1730.990] there yet because it doesn't
[1731.000-1732.950] fully work or it's a scale issue and we
[1732.960-1734.149] just haven't like figured out how to use
[1734.159-1735.790] it. So you know, it's hard to tell. Can
[1735.800-1737.630] I ask a somewhat blasphemous question
[1737.640-1740.310] which is like if this jaggedness is
[1740.320-1741.870] persisting
[1741.880-1744.149] and it's all rolled up in a
[1744.159-1745.830] at least monolithic interface, right?
[1745.840-1748.470] But you know, single model.
[1748.480-1750.310] Does that make sense or do you should
[1750.320-1751.710] should it be unbundled into things that
[1751.720-1753.710] are can be optimized and improved
[1753.720-1755.870] against different domains of
[1755.880-1757.950] intelligence? Like unbundling the models
[1757.960-1759.270] into multiple experts in different
[1759.280-1762.190] areas, etc. More directly. Yeah. Um
[1762.200-1764.230] Instead of just MOE that we have no
[1764.240-1765.909] exposure to because that can be like
[1765.919-1768.149] confusing as a user from the outside
[1768.159-1769.630] which is like why is it so good at this,
[1769.640-1771.669] but not at this other thing? Yeah, I
[1771.679-1773.510] think currently my impression is the
[1773.520-1774.790] labs are trying to have a single sort of
[1774.800-1777.070] like monoculture of a model that is
[1777.080-1779.270] arbitrarily intelligent in all these
[1779.280-1780.870] different domains and they just stuff it
[1780.880-1782.909] into the parameters. I do think that we
[1782.919-1784.710] will we I do think we should expect more
[1784.720-1786.830] speciation in the
[1786.840-1788.150] intelligences.
[1788.160-1789.270] Um
[1789.280-1790.990] like, you know, the animal kingdom is
[1791.000-1792.350] extremely diverse in the brains that
[1792.360-1793.870] exist and there's lots of different
[1793.880-1796.670] niches of of nature and some animals
[1796.680-1798.470] have overdeveloped visual cortex or
[1798.480-1800.870] other part kind of parts and I think we
[1800.880-1803.030] we should be able to see more speciation
[1803.040-1804.950] and um you don't need like this oracle
[1804.960-1806.510] that knows everything. You can speciate
[1806.520-1807.910] it and then you put it on a specific
[1807.920-1809.110] task and we should be seeing some of
[1809.120-1810.670] that because you should be able to have
[1810.680-1811.950] like much smaller models that still have
[1811.960-1813.310] the cognitive core like they're still
[1813.320-1815.190] competent but then they specialize and
[1815.200-1817.750] then um and then they they can become
[1817.760-1819.670] more efficient in terms of latency or
[1819.680-1820.990] throughput on
[1821.000-1822.110] specific tasks that you really care
[1822.120-1823.350] about. Like if you're a mathematician
[1823.360-1824.950] working in Lean, I saw for example
[1824.960-1826.270] there's a few releases that really like
[1826.280-1828.550] target that as a domain. Um
[1828.560-1829.950] uh so there's a probably going to be a
[1829.960-1831.350] few examples like that where the
[1831.360-1833.310] unbundling kind of makes sense. One
[1833.320-1836.190] question I have is whether or not the
[1836.200-1838.990] capacity constraint on available compute
[1839.000-1841.310] infrastructure Mhm. drives more of this
[1841.320-1843.150] because efficiency Yeah. actually
[1843.160-1844.990] matters more. Yeah.
[1845.000-1847.390] Your if you
[1847.400-1849.230] financing aside, though financing's
[1849.240-1850.550] involved in all of this. If you have
[1850.560-1852.710] access to full compute for anything you
[1852.720-1855.550] do like even one single model, right?
[1855.560-1857.390] But if you actually feel pressure where
[1857.400-1859.550] you're like I can't serve
[1859.560-1861.230] &gt;&gt; Mhm. um
[1861.240-1863.150] model of massive size for every use
[1863.160-1863.630] case.
[1863.640-1865.230] &gt;&gt; Mhm. Like do you think that leads to any
[1865.240-1866.750] speciation? Does that question make
[1866.760-1868.270] sense to you? The question makes sense
[1868.280-1870.190] and I guess like what I'm what I'm what
[1870.200-1871.830] I what I'm struggling with is I don't
[1871.840-1873.110] think we've seen too much speciation
[1873.120-1875.230] just yet, right? No. Uh we're seeing a
[1875.240-1877.550] monoculture of models. Yeah. So um And
[1877.560-1879.190] there's like clearly pressure for like
[1879.200-1880.710] make a good code model, put it back in
[1880.720-1883.030] the main, merge again. Yeah.
[1883.040-1885.710] &gt;&gt; Um
[1887.230-1887.240] even though there already is pressure on
[1887.240-1889.470] the models. Mhm. I guess perhaps I I
[1889.480-1890.630] feel like there's a lot of very
[1890.640-1893.150] short-term supply crunch and like maybe
[1893.160-1895.510] that causes more speciation now.
[1895.520-1897.950] Yeah, I think fundamentally like the
[1897.960-1899.870] the the labs are serving a model and
[1899.880-1901.750] they don't really know what the end user
[1901.760-1903.870] is going to be asking about. So maybe
[1903.880-1905.190] that's like some part of it because they
[1905.200-1906.350] kind of have to multitask over all the
[1906.360-1907.990] possible things they could be asked. But
[1908.000-1909.110] I think if you're coming to a business
[1909.120-1910.710] and maybe partnering on some specific
[1910.720-1912.350] problems you care about then maybe you
[1912.360-1914.669] would see that there. Um or there would
[1914.679-1916.310] be some very high-value applications
[1916.320-1918.430] that are like more niche. Um
[1918.440-1920.310] But but I think right now they're kind
[1920.320-1921.669] of like going after the totality of
[1921.679-1923.230] what's available. I don't think that the
[1923.240-1925.870] science of manipulating the brains is
[1925.880-1927.590] like fully developed yet partly. What do
[1927.600-1929.590] you mean manipulating? So like so
[1929.600-1931.430] fine-tuning without losing capabilities
[1931.440-1933.070] as an example. And I we don't have these
[1933.080-1934.230] primitives for actually like working
[1934.240-1935.910] with the intelligences in ways other
[1935.920-1937.510] than just context windows. Our context
[1937.520-1939.430] windows kind of just just work and it's
[1939.440-1940.830] very cheap to manipulate etc. And this
[1940.840-1941.590] is how we're getting some of the
[1941.600-1943.910] customization etc. Uh but I think if it
[1943.920-1946.470] was I think it's a it's a bit more of a
[1946.480-1947.870] developing science of how you like more
[1947.880-1949.910] deeply adjust the models, how you have
[1949.920-1952.470] continual learning maybe or how you
[1952.480-1954.030] um how you fine-tune in a certain area,
[1954.040-1955.390] how you get better in a certain area or
[1955.400-1956.750] like how you actually touch the weights
[1956.760-1958.350] not just the context windows. And so
[1958.360-1959.669] it's a lot more
[1959.679-1961.150] tricky I would say to touch the weights
[1961.160-1963.030] than just the context windows uh because
[1963.040-1964.070] you're actually fundamentally changing
[1964.080-1965.430] the full model and potentially its
[1965.440-1967.990] intelligence. And so um
[1968.000-1969.230] so maybe it's just like not a fully
[1969.240-1970.510] developed science if that makes sense of
[1970.520-1973.070] speciation. And it also has to be like
[1973.080-1975.270] cheap enough Yeah. for that speciation
[1975.280-1977.510] to be worthwhile in these given
[1977.520-1979.950] &gt;&gt; contexts. Can I ask a question about
[1979.960-1982.310] like an extension to auto research that
[1982.320-1984.630] you described in terms of open ground?
[1984.640-1986.190] You say okay, well, you know, we have
[1986.200-1988.750] this thing. Um we need more
[1988.760-1990.510] collaboration surface around it
[1990.520-1993.430] essentially for people to contribute
[1993.440-1995.270] to research overall. Can you talk about
[1995.280-1995.669] that?
[1995.679-1996.750] &gt;&gt; Yeah, so we talked about auto research
[1996.760-1998.070] has a single thread of like I'm going to
[1998.080-2000.710] try stuff in a loop but fundamentally
[2000.720-2002.070] the parallelization of this is like the
[2002.080-2003.950] interesting component.
[2003.960-2004.990] And I guess I was trying to like play
[2005.000-2006.710] around with a few ideas but I don't have
[2006.720-2008.550] anything that like clicks as simply as
[2008.560-2009.710] like I don't have something I'm like
[2009.720-2010.790] super happy with just yet but it's
[2010.800-2012.590] something I'm like working on the side
[2012.600-2014.830] when I'm not working on my claw.
[2014.840-2015.790] Um
[2015.800-2018.030] so I think like one issue is if you have
[2018.040-2020.070] a bunch of nodes
[2020.080-2021.790] of parallelization available to then
[2021.800-2023.150] it's very easy to just have multiple
[2023.160-2025.270] auto researchers talking through a
[2025.280-2026.870] a common system or something like that.
[2026.880-2028.030] What I was more interested in is how you
[2028.040-2029.830] can have an untrusted pool of workers
[2029.840-2031.510] out there on the internet. Mhm. So for
[2031.520-2033.669] example in auto research
[2033.679-2036.510] you're just trying to find um
[2036.520-2038.150] the piece of code that trains a model to
[2038.160-2040.630] a very low validation loss.
[2040.640-2042.710] If anyone gives you a candidate commit,
[2042.720-2044.350] it's very easy to verify that that
[2044.360-2046.669] commit is correct is good. Like they
[2046.679-2047.830] someone could claim from the internet
[2047.840-2049.869] that this piece of code will optimize
[2049.879-2050.909] much better and give you much better
[2050.919-2052.950] performance. You could just check. Yeah.
[2052.960-2054.950] But probably a lot of work goes into
[2054.960-2055.990] that checking.
[2056.000-2057.590] But fundamentally they could lie and
[2057.600-2059.389] etc. So you're basically dealing with a
[2059.399-2060.630] similar kind of it's almost actually
[2060.640-2062.230] like looks a little bit like my my
[2062.240-2063.830] designs that incorporate an untrusted
[2063.840-2065.110] pool of workers
[2065.120-2066.470] actually look a little bit more like a
[2066.480-2068.630] blockchain a little bit uh because
[2068.640-2071.149] instead of blocks you have commits and
[2071.159-2072.190] these commits can build on each other
[2072.200-2073.510] and they contain like changes to the
[2073.520-2076.950] code as you're improving it. Um and uh
[2076.960-2078.310] the proof of work is basically doing
[2078.320-2079.550] tons of experimentation to find the
[2079.560-2080.950] commits that work.
[2080.960-2082.950] Um and that's hard
[2082.960-2084.270] and then the reward is just being on the
[2084.280-2085.869] leaderboard right now. There's no
[2085.879-2087.669] monetary reward whatsoever.
[2087.679-2088.950] Uh but I don't want to push the analogy
[2088.960-2090.470] too far but it fundamentally has this
[2090.480-2091.590] issue where
[2091.600-2093.310] you a huge amount of search goes into it
[2093.320-2095.310] but it's very cheap to verify that a
[2095.320-2097.030] candidate solution is indeed good
[2097.040-2098.710] because you can just train a single you
[2098.720-2100.230] know, someone had to try 10,000 ideas
[2100.240-2101.030] but
[2101.040-2102.030] you just have to check that the thing
[2102.040-2103.510] that they produced actually works
[2103.520-2105.710] because the 99,000 of them didn't work,
[2105.720-2108.910] you know? Um and so basically long story
[2108.920-2110.110] short is like you have to come up with a
[2110.120-2112.790] system where an untrusted pool of
[2112.800-2114.870] workers can collaborate with a trusted
[2114.880-2116.750] pool of workers that do the
[2116.760-2117.990] verification.
[2118.000-2119.349] And the whole thing is kind of like
[2119.359-2122.070] asynchronous and works and
[2122.080-2124.550] and so on and it's it's like safe from a
[2124.560-2125.910] security perspective because if anyone
[2125.920-2127.070] sends you arbitrary code and you're
[2127.080-2128.630] going to run it, that is very sketchy
[2128.640-2130.870] and dodgy. So um
[2130.880-2131.950] but fundamentally it should be totally
[2131.960-2132.910] possible. So you're familiar with
[2132.920-2134.110] projects like SETI@home and
[2134.120-2135.870] Folding@home. All of these problems have
[2135.880-2138.070] a similar kind of setup. So Folding@home
[2138.080-2139.910] you're folding a protein
[2139.920-2140.790] and it's very hard to find a
[2140.800-2142.430] configuration that is low energy. But if
[2142.440-2143.750] someone finds a configuration that they
[2143.760-2145.270] value to be low energy, that's perfect.
[2145.280-2146.270] You can just use it. You can easily
[2146.280-2147.310] verify it.
[2147.320-2148.510] So a lot of things have this property
[2148.520-2150.110] that you know, very expensive to come up
[2150.120-2152.670] with but very cheap to verify. And so in
[2152.680-2154.550] all those cases things like Folding@home
[2154.560-2157.070] or SETI@home or auto research at home
[2157.080-2160.110] will be good fits. And so um long story
[2160.120-2161.150] short
[2161.160-2163.150] a swarm of agents on the internet could
[2163.160-2165.790] collaborate to improve LLMs and could
[2165.800-2167.430] potentially even like run circles around
[2167.440-2169.590] frontier labs. Like who knows, you know?
[2169.600-2170.830] Um
[2170.840-2172.190] yeah, like maybe that's even possible.
[2172.200-2173.790] Like frontier labs have a huge amount of
[2173.800-2176.430] trusted compute but the earth is much
[2176.440-2177.990] bigger and has huge amount of untrusted
[2178.000-2180.550] compute. But if you put systems in check
[2180.560-2182.310] systems in place that you know, deal
[2182.320-2184.710] with this then maybe it is possible that
[2184.720-2186.750] the swarm out there could could come up
[2186.760-2189.550] with with better with better solutions.
[2189.560-2190.750] And people kind of like contribute
[2190.760-2192.470] cycles um
[2192.480-2194.510] to to a thing that they care about. And
[2194.520-2196.670] so sorry to so the last thought is
[2196.680-2197.950] uh lots of companies or whatnot they
[2197.960-2199.510] could maybe have like their own things
[2199.520-2201.390] that they care about and you if you have
[2201.400-2203.270] compute capacity you could contribute to
[2203.280-2204.910] different kind of auto research tracks.
[2204.920-2206.590] Like maybe you care about certain you
[2206.600-2208.310] know, like you care about like cancer or
[2208.320-2209.750] something like that of certain type. You
[2209.760-2210.750] don't have to just donate money to an
[2210.760-2212.349] institution. You actually could like
[2212.359-2214.430] purchase compute and then you could join
[2214.440-2215.910] the auto research swarm for that
[2215.920-2218.670] project, you know? Uh so if everything
[2218.680-2220.670] is rebundled into auto researchers then
[2220.680-2221.670] compute becomes the thing that you're
[2221.680-2223.670] contributing to the pool. Yeah. That's
[2223.680-2224.950] very inspiring and it's also
[2224.960-2226.390] interesting. Like I don't I don't know
[2226.400-2228.670] how far this goes but it is interesting
[2228.680-2231.430] that at least some audience of people
[2231.440-2233.110] you know, here in Silicon Valley or
[2233.120-2235.470] lining up at you know, retail stores in
[2235.480-2238.070] China have discovered that like having
[2238.080-2239.670] access to personal compute is
[2239.680-2240.470] interesting again.
[2240.480-2241.870] &gt;&gt; Yeah. Right? So maybe they're really
[2241.880-2243.910] motivated to do that for their claws and
[2243.920-2245.430] then they can contribute to auto
[2245.440-2245.950] research.
[2245.960-2247.590] &gt;&gt; almost like dollars the thing everyone
[2247.600-2249.790] cares about but is flop the thing that
[2249.800-2251.110] actually everyone cares about in the
[2251.120-2252.349] future? Like is there going to be like a
[2252.359-2254.030] flipening almost of like what's the
[2254.040-2255.150] thing that you care about? Like right
[2255.160-2256.310] now for example it's really hard to get
[2256.320-2258.670] compute even if you have money. Yeah.
[2258.680-2260.030] So actually it almost seems like the
[2260.040-2261.731] flop is like dominant
[2261.741-2262.270] &gt;&gt; [laughter]
[2262.280-2264.430] &gt;&gt; in a certain sense. Um
[2264.440-2266.110] Yeah, so so maybe that's kind of like
[2266.120-2267.910] that. Kind of like that. Like how much
[2267.920-2269.230] how many flops do you control instead of
[2269.240-2271.030] like what wealth you control? I don't
[2271.040-2272.190] actually think that's true but it's kind
[2272.200-2274.190] of interesting to think about. The last
[2274.200-2275.710] thing you released was like a little bit
[2275.720-2278.510] of jobs data analysis. Is that right?
[2278.520-2279.790] What
[2279.800-2281.430] and might have touched a nerve even
[2281.440-2282.750] though you're just like visualizing some
[2282.760-2283.430] public data.
[2283.440-2285.349] &gt;&gt; Yeah. Uh what was you know, what were
[2285.359-2286.830] you curious about? Yeah, I guess I was
[2286.840-2289.070] curious to um
[2289.080-2290.590] I mean everyone is like really it's
[2290.600-2291.510] everyone is really thinking about the
[2291.520-2293.310] impacts of AI on the job market and
[2293.320-2295.190] what's going to look like. So I was just
[2295.200-2296.430] interested to take a look like what does
[2296.440-2297.670] the job market look like? Where are the
[2297.680-2299.550] different roles um
[2299.560-2300.630] and how many people are in different
[2300.640-2302.070] professions? And I was like really just
[2302.080-2304.030] interested to like look through
[2304.040-2305.550] the individual cases and try to think
[2305.560-2307.590] myself about like you know, with these
[2307.600-2309.110] AIs and how they're likely to evolve
[2309.120-2310.390] like
[2310.400-2311.670] are these going to be tools that people
[2311.680-2313.070] are using? Are these going to be
[2313.080-2315.990] displacing tools for these professions?
[2316.000-2317.270] And like what are the current
[2317.280-2318.710] professions and how are they going to
[2318.720-2320.830] change? Are they going to grow or uh
[2320.840-2322.349] adjust to a large extent or like what
[2322.359-2323.790] could be new professions? So it's really
[2323.800-2325.270] just like a way to fuel my own chain of
[2325.280-2327.230] thought about the industry I suppose.
[2327.240-2329.910] Mhm. Um and so
[2329.920-2331.190] yeah, the jobs data basically is just a
[2331.200-2333.070] Bureau of Labor Statistics. They
[2333.080-2335.870] actually have um percent outlook for
[2335.880-2337.390] each profession about how much it's
[2337.400-2338.870] expected to grow over the next I think
[2338.880-2340.710] almost a decade. Uh yeah, I think it's a
[2340.720-2342.790] decade but it was made in 2024. Mhm. We
[2342.800-2344.910] need a lot of health care workers. Yeah.
[2344.920-2346.190] So so they've already made those
[2346.200-2347.670] projections and I'm not sure actually
[2347.680-2349.630] 100% what the methodology was that they
[2349.640-2351.910] they put into their projections. Um I
[2351.920-2353.590] guess I was interested to color things
[2353.600-2355.630] by like if people think that what's like
[2355.640-2357.110] primarily being
[2357.120-2358.430] developed now is this kind of like more
[2358.440-2360.110] digital AI
[2360.120-2361.310] that is kind of like almost like these
[2361.320-2363.150] ghosts or spirit entities that can like
[2363.160-2365.390] interact in the digital world and
[2365.400-2366.510] manipulate a lot of like digital
[2366.520-2367.990] information and they currently don't
[2368.000-2369.710] really have a physical embodiment or
[2369.720-2371.150] presence. And the physical stuff is
[2371.160-2372.390] probably going to go slightly slower
[2372.400-2374.150] because you're manipulating atoms. So
[2374.160-2375.990] flipping flipping bits and
[2376.000-2377.870] and the ability to copy-paste digital
[2377.880-2379.550] information is like makes everything a
[2379.560-2381.510] million times faster than accelerating
[2381.520-2383.310] matter, you know, so
[2383.320-2385.230] Um so energetically, I just think we're
[2385.240-2386.630] going to see a huge amount of activity
[2386.640-2388.070] in the digital space, huge amount of
[2388.080-2390.110] rewriting, huge amount of activity,
[2390.120-2392.550] boiling soup. And I think the we're
[2392.560-2393.870] going to see something that in the
[2393.880-2395.150] digital space goes at the speed of light
[2395.160-2396.150] compared to I think what's going to
[2396.160-2397.350] happen in the physical world to some
[2397.360-2398.950] extent. If it would be the
[2398.960-2401.247] extrapolation. And so I think like
[2401.257-2401.790] &gt;&gt; [clears throat]
[2401.800-2403.510] &gt;&gt; there's currently kind of like I think
[2403.520-2406.030] overhang where there can be like a lot
[2406.040-2408.110] of unhubbling almost potentially of like
[2408.120-2409.870] a lot of digital information processing
[2409.880-2411.630] that used to be done by computers and
[2411.640-2413.190] people. And now with AIs there's like a
[2413.200-2414.550] third kind of manipulator of digital
[2414.560-2415.670] information. There's going to be a lot
[2415.680-2417.990] of refactoring in those in those
[2418.000-2419.070] disciplines.
[2419.080-2420.990] Um but the physical world is actually
[2421.000-2422.830] going to be like I think
[2422.840-2424.950] behind that by some amount of time. And
[2424.960-2425.870] so I think what's really fascinating to
[2425.880-2427.630] me is like
[2427.640-2429.030] So that's why I was highlighting the the
[2429.040-2430.470] professions that fundamentally
[2430.480-2431.790] manipulate digital information. This is
[2431.800-2433.910] work you could do from your home, etc.
[2433.920-2435.190] Uh because I feel like those will be
[2435.200-2436.710] like things will change. And it doesn't
[2436.720-2438.110] mean that there's going to be less of
[2438.120-2439.630] those jobs or more of those jobs because
[2439.640-2440.790] it does has to do with like demand
[2440.800-2442.710] elasticity and many other factors. But
[2442.720-2444.230] things will change in these professions
[2444.240-2446.830] because of these new tools and um
[2446.840-2448.110] because of this upgrade to the nervous
[2448.120-2450.373] system of the human superorganism
[2450.383-2450.630] &gt;&gt; [laughter]
[2450.640-2452.030] &gt;&gt; if you want to think about it that way.
[2452.040-2453.630] Given the look you had at the data, do
[2453.640-2457.110] you have either any observations or um
[2457.120-2459.510] uh guidance for people facing the job
[2459.520-2461.110] market or thinking about what to study
[2461.120-2463.110] now or what skills to develop? I mean we
[2463.120-2465.710] can all go get like I'm very thankful
[2465.720-2466.870] that I have to like meet people for my
[2466.880-2467.830] job right now.
[2467.840-2468.058] &gt;&gt; Yeah.
[2468.068-2468.110] &gt;&gt; [laughter]
[2468.120-2470.150] &gt;&gt; Yeah, more physical. Yeah. Could you do
[2470.160-2473.070] your work from home though? I could.
[2473.080-2474.310] I think there are relationship parts of
[2474.320-2475.790] it that are hard, but most of it I
[2475.800-2477.270] could. Yeah. I think it's really hard to
[2477.280-2478.470] tell because again like the job market
[2478.480-2479.790] is extremely diverse. I think the
[2479.800-2481.790] answers will probably vary, but uh to a
[2481.800-2482.950] large extent like these tools are
[2482.960-2484.470] extremely new, extremely powerful. And
[2484.480-2486.030] so just being you know, just trying to
[2486.040-2488.670] keep up with it is like the first thing.
[2488.680-2489.510] Um
[2489.520-2491.350] and um
[2491.360-2492.310] yeah, because I think a lot of people
[2492.320-2494.070] kind of like dismiss it or Or they're
[2494.080-2495.470] afraid of it. Or they're afraid of it,
[2495.480-2497.470] etc. As which is totally understandable,
[2497.480-2499.510] of course. Yeah, I think like um
[2499.520-2500.990] it's fundamentally an empowering tool at
[2501.000-2503.510] the moment. Um and these jobs are
[2503.520-2504.790] bundles of tasks. And some of these
[2504.800-2506.230] tasks can go a lot faster. And so people
[2506.240-2507.350] should think of it as primarily a tool
[2507.360-2508.710] that it is right now.
[2508.720-2510.670] Um and I think the long-term future of
[2510.680-2512.510] that is uncertain. Yeah, it's kind of
[2512.520-2514.470] really hard to forecast, to be honest.
[2514.480-2516.030] And like I'm not professionally like
[2516.040-2517.350] doing that really. And I think this is a
[2517.360-2519.710] job of like economists to do properly.
[2519.720-2522.190] You are an engineer though. And like one
[2522.200-2523.510] thing I thought was interesting is that
[2523.520-2524.430] like
[2524.440-2526.830] the demand for engineering jobs
[2526.840-2528.150] is continuing to increase.
[2528.160-2530.350] &gt;&gt; Yeah. Um I I can't tell if that's like a
[2530.360-2531.710] temporary phenomenon. I'm not sure how I
[2531.720-2533.350] feel about it. Yeah, do you know? Yeah,
[2533.360-2534.830] that's like the demand elasticity almost
[2534.840-2537.510] like uh software was scarce, right? And
[2537.520-2539.310] so the reason we don't have more demand
[2539.320-2540.630] for software is just there's its
[2540.640-2542.310] scarcity and it's too expensive.
[2542.320-2543.510] &gt;&gt; So if the barrier comes down, then
[2543.520-2545.350] actually you have the Jevons paradox,
[2545.360-2546.510] which is like you know, you actually the
[2546.520-2547.910] demand for software actually goes up.
[2547.920-2549.430] It's cheaper and there's more More
[2549.440-2551.310] powerful, yeah. The the classical
[2551.320-2553.510] example of this always is the ATMs and
[2553.520-2554.870] the bank tellers
[2554.880-2556.470] uh because there was a lot of like fear
[2556.480-2559.790] that um ATMs and computers basically uh
[2559.800-2561.430] would displace tellers. But what
[2561.440-2562.950] happened is they made like the cost of
[2562.960-2564.430] operation of
[2564.440-2566.670] of a bank branch much cheaper. And so
[2566.680-2567.710] there are more bank branches, so there
[2567.720-2569.430] are more tellers. It's like the
[2569.440-2571.390] canonical example people cite. Uh but
[2571.400-2572.790] basically it's just Jevons paradox. Like
[2572.800-2575.190] something becomes cheaper, so there's
[2575.200-2577.630] a lot of unlocked demand for it. Uh so I
[2577.640-2579.750] do think that that's probably I do have
[2579.760-2581.470] like cautiously optimistic view of this
[2581.480-2582.910] in software engineering
[2582.920-2585.070] where I do think um it does seem to me
[2585.080-2586.110] like the demand for software will be
[2586.120-2588.630] extremely large. Um and it's just become
[2588.640-2591.830] a lot cheaper. And um
[2591.840-2594.470] so I do think that for quite some time
[2594.480-2595.710] um
[2595.720-2597.390] it's very hard to forecast, but it does
[2597.400-2598.390] seem to me like right now at least
[2598.400-2599.710] locally there's going to be more demand
[2599.720-2600.830] for software.
[2600.840-2602.190] Um because software is amazing. It's
[2602.200-2603.150] like you know, digital information
[2603.160-2604.990] processing. You're not forced to use
[2605.000-2606.310] like arbitrary tools that were given to
[2606.320-2607.750] you. They're imperfect in various ways.
[2607.760-2609.510] You're not forced to subscribe to what
[2609.520-2611.910] exists. Code is now ephemeral and it can
[2611.920-2613.870] change and it can be modified.
[2613.880-2614.470] Um
[2614.480-2615.830] and so I think there's going to be a lot
[2615.840-2618.190] of activity in the digital space to like
[2618.200-2620.070] rewire everything in a certain sense.
[2620.080-2620.910] And I think it's going to create a lot
[2620.920-2622.990] of demand for for this kind of stuff. I
[2623.000-2625.590] think long-term um yeah, obviously even
[2625.600-2628.190] with auto research like OpenAI or or you
[2628.200-2630.190] know, Anthropic or these other labs like
[2630.200-2631.790] they're employing what like a thousand
[2631.800-2633.110] something researchers, right?
[2633.120-2634.510] &gt;&gt; Mhm. These researchers are basically
[2634.520-2637.050] like glorified auto like you know.
[2637.060-2638.070] &gt;&gt; [laughter]
[2638.080-2639.390] &gt;&gt; They're like automating themselves away
[2639.400-2640.750] like actively and this is like the thing
[2640.760-2642.830] they're all trying to do. Yeah. I
[2642.840-2644.510] like I went around um Some of those
[2644.520-2646.030] researchers also fear that feel the
[2646.040-2647.950] psychosis, right? Because they can it's
[2647.960-2650.470] working, right? And and so they're like
[2650.480-2652.030] it's over for me, too. I did spend a
[2652.040-2653.349] bunch of time going around OpenAI and I
[2653.359-2654.470] was like, you guys realize if we're
[2654.480-2655.950] successful like we're all out of job
[2655.960-2656.910] like
[2656.920-2657.750] like this is just going to we're just
[2657.760-2659.630] building automation for Sam or something
[2659.640-2661.630] like that. Like I or the board or I'm
[2661.640-2663.830] not sure, but like uh they're just
[2663.840-2665.790] building all this automation for yeah,
[2665.800-2667.230] the board or the CEO or something like
[2667.240-2669.310] that. And we're all out of our job and
[2669.320-2670.150] maybe
[2670.160-2672.830] contributing on the side. And so
[2672.840-2674.510] yeah, it's kind of like unnerving from
[2674.520-2676.190] that perspective. Is it okay if I ask
[2676.200-2678.310] you Noam's question? Mhm. You know, you
[2678.320-2680.270] could be doing that, right? Auto
[2680.280-2682.150] researching with a lot of compute scale
[2682.160-2683.390] and a bunch of colleagues at one of the
[2683.400-2684.470] frontier [clears throat] labs. Like why
[2684.480-2686.150] not? Well, I was there for a while,
[2686.160-2688.390] right? Like and I did reenter. So to
[2688.400-2689.790] some extent I agree and I think that
[2689.800-2690.750] there are many ways to slice this
[2690.760-2692.230] question. It's very loaded question a
[2692.240-2694.790] little bit. Um I will say that I feel
[2694.800-2696.190] very good about like what people can
[2696.200-2698.710] contribute and their impact outside of
[2698.720-2700.590] the frontier labs, obviously. Not in the
[2700.600-2702.150] industry, but also in like more like
[2702.160-2705.110] ecosystem level roles. Um so your role
[2705.120-2706.230] for example is more like ecosystem
[2706.240-2707.630] level. My role currently is also kind of
[2707.640-2709.230] more on ecosystem level. And I feel very
[2709.240-2710.470] good about like impact that people can
[2710.480-2712.470] have in those kinds of roles. I think
[2712.480-2714.110] conversely there's there are definite
[2714.120-2717.190] problems in my mind for um uh for
[2717.200-2718.550] basically aligning yourself way too much
[2718.560-2720.070] with the frontier labs, too. So
[2720.080-2721.630] fundamentally I mean you're you have a
[2721.640-2723.950] huge amount of financial incentive to uh
[2723.960-2725.390] with these frontier labs. And by your
[2725.400-2727.670] own admission, the uh the AIs are going
[2727.680-2729.390] to like really change humanity and
[2729.400-2731.510] society in very dramatic ways. And here
[2731.520-2733.349] you are basically like building the
[2733.359-2735.150] technology and benefiting from it like
[2735.160-2736.550] it and being like very allied to it
[2736.560-2738.310] through financial means. Like this was
[2738.320-2740.470] the conundrum that was in at the heart
[2740.480-2742.470] of you know, how OpenAI was started in
[2742.480-2743.390] the beginning. Like this was the
[2743.400-2744.830] conundrum that we were trying to solve.
[2744.840-2747.790] Mhm. Um and so you know, that
[2747.800-2749.790] so it's kind of um It's still not
[2749.800-2750.510] resolved.
[2750.520-2751.790] &gt;&gt; is still not like fully resolved. So
[2751.800-2753.470] that's number one. You're you're not a
[2753.480-2754.710] completely free agent and you can't
[2754.720-2755.630] actually like be part of that
[2755.640-2758.190] conversation in a fully autonomous um
[2758.200-2759.910] free way. Like if you're inside one of
[2759.920-2761.390] the frontier labs. Like there's some
[2761.400-2763.070] things that you can't say. Uh and
[2763.080-2764.230] conversely there are some things that
[2764.240-2766.230] the organization wants you to say. And
[2766.240-2767.070] you know, they're not going to twist
[2767.080-2768.550] your arm, but
[2768.560-2769.950] you feel the pressure of like what you
[2769.960-2771.390] should be saying,
[2771.400-2773.946] you know, cuz like obviously
[2773.956-2774.710] &gt;&gt; [laughter]
[2774.720-2775.830] &gt;&gt; otherwise it's like really awkward
[2775.840-2777.430] conversations,
[2777.440-2778.750] uh strange side eyes, like what are you
[2778.760-2780.590] doing, you know, like so you can't like
[2780.600-2782.390] really be an independent agent. And I I
[2782.400-2784.390] feel like a bit more a lot like aligned
[2784.400-2785.870] with humanity in a certain sense outside
[2785.880-2787.710] of the frontier lab because
[2787.720-2788.950] I don't I'm not subject to those
[2788.960-2790.349] pressures almost, right? And I can say
[2790.359-2791.950] whatever I want or Yeah, I would say in
[2791.960-2794.310] the frontier labs like um
[2794.320-2795.710] you can have like
[2795.720-2797.710] impact there of course as well. So
[2797.720-2799.150] but there's many researchers and maybe
[2799.160-2800.310] you're one of them, maybe your ideas are
[2800.320-2801.910] really good, etc. Maybe there's a lot of
[2801.920-2803.349] decision-making to do and you want to be
[2803.359-2804.550] in a position where you are in the room
[2804.560-2805.670] with those conversations when they come
[2805.680-2807.190] up. I do think that currently the stakes
[2807.200-2808.990] are like overall fairly low and so
[2809.000-2810.830] everything is kind of like nice. But
[2810.840-2812.110] ultimately in the end of the day like
[2812.120-2813.830] when the stakes are really high, etc. If
[2813.840-2815.270] you're an employee at an organization, I
[2815.280-2816.510] don't actually know how much sway you're
[2816.520-2817.830] going to have on your organization what
[2817.840-2819.070] it's going to do. Like fundamentally at
[2819.080-2820.990] the end of the day um
[2821.000-2823.310] uh it's uh you're not like really in
[2823.320-2824.349] charge. Like you're in the room and
[2824.359-2825.710] you're contributing ideas, but you're
[2825.720-2827.070] not like really in charge of that entity
[2827.080-2828.590] that you're that you're part of. So
[2828.600-2829.630] those are like some sources of
[2829.640-2831.470] misalignment, I think to some extent. I
[2831.480-2833.630] will say that like in one way I do agree
[2833.640-2836.470] a lot with that sentiment that um I do
[2836.480-2837.750] feel like in the
[2837.760-2838.870] like the labs for better or worse
[2838.880-2840.190] they're opaque and a lot of work is
[2840.200-2841.910] there. And they're kind of like at the
[2841.920-2843.310] edge of capability and what's possible.
[2843.320-2844.590] And they're working on what's coming
[2844.600-2846.110] down the line. And I think if you're
[2846.120-2848.670] outside of that frontier lab, your your
[2848.680-2849.910] judgment fundamentally will start to
[2849.920-2852.150] drift because you're not part of the
[2852.160-2853.070] you know,
[2853.080-2854.670] what's coming down the line. And so I
[2854.680-2856.110] feel like my judgment will inevitably
[2856.120-2857.990] start to drift as well. And I won't
[2858.000-2858.990] actually have an understanding of how
[2859.000-2860.190] these systems actually work under the
[2860.200-2862.070] hood. That's an opaque system.
[2862.080-2863.790] I won't have a a good understanding of
[2863.800-2865.710] how it's going to develop and etc. And
[2865.720-2868.030] so I do think that in that sense I agree
[2868.040-2869.510] and something I'm nervous about. I think
[2869.520-2871.390] it's worth basically
[2871.400-2872.470] being in touch with what's actually
[2872.480-2873.630] happening and actually being in a
[2873.640-2875.349] frontier lab. And if if some of the
[2875.359-2877.230] frontier labs would have me come for you
[2877.240-2878.630] know, some amount of time and do really
[2878.640-2880.430] good work for them and then maybe come
[2880.440-2880.790] and hang out.
[2880.800-2881.910] &gt;&gt; looking for a job. This is super
[2881.920-2883.510] exciting. [laughter]
[2883.520-2885.070] Then I think that's maybe a good setup
[2885.080-2886.430] because I kind of feel like it's kind of
[2886.440-2886.990] um
[2887.000-2888.670] you know,
[2888.680-2890.750] maybe that's like one way Mhm. uh to to
[2890.760-2892.349] actually be connected to what's actually
[2892.359-2893.670] happening, but also not feel like you're
[2893.680-2895.830] necessarily fully controlled by Yeah. by
[2895.840-2897.550] those entities. So I think
[2897.560-2899.230] honestly in my mind like
[2899.240-2901.070] Noam can probably get do extremely good
[2901.080-2903.110] work at at OAI, but also I think his
[2903.120-2905.190] most impactful work could very well be
[2905.200-2907.030] outside of OpenAI. Noam, that's a call
[2907.040-2908.710] to be an independent researcher with
[2908.720-2910.310] auto [laughter] research.
[2910.320-2911.190] Yeah, there's many things to do on the
[2911.200-2913.349] outside and it's it's a
[2913.359-2915.030] and I think ultimately I think the ideal
[2915.040-2916.870] solution maybe is like yeah, going back
[2916.880-2917.990] and forth
[2918.000-2919.790] or um
[2919.800-2920.870] yeah, and I think fundamentally you can
[2920.880-2922.190] have a really amazing impact in both
[2922.200-2923.870] places. So very complicated I don't
[2923.880-2925.390] know. Like it's a very loaded question a
[2925.400-2926.950] little bit, but I mean I joined the
[2926.960-2928.630] frontier lab and I'm outside. And then
[2928.640-2929.990] maybe in the future I'll want to join
[2930.000-2932.870] again. And I think um
[2932.880-2934.430] uh that's kind of like how I look at it.
[2934.440-2937.110] One question related to what visibility
[2937.120-2940.070] to does the world or the AI ecosystem
[2940.080-2941.750] have into
[2941.760-2944.710] the frontier is like how how close open
[2944.720-2947.030] source is to the frontier. Mhm. Um and
[2947.040-2949.830] how sustainable that is. I I think Yeah.
[2949.840-2952.630] I think it is quite surprising. The
[2952.640-2954.230] entire sequence of events actually from
[2954.240-2957.270] like having a handful of Chinese models
[2957.280-2959.590] and global models and I think people are
[2959.600-2960.910] going to continue releasing here in the
[2960.920-2963.470] near term that are closer than much of
[2963.480-2964.870] the industry anticipated from a
[2964.880-2966.190] capability [clears throat] perspective.
[2966.200-2967.230] &gt;&gt; Yeah. Um I don't know if you're
[2967.240-2968.190] surprised by that, but you're a
[2968.200-2969.470] long-term contributor to open source.
[2969.480-2971.150] Like what's your prediction here? Yeah,
[2971.160-2973.790] so roughly speaking basically the
[2973.800-2975.390] the closed models are ahead, but like
[2975.400-2976.430] people are monitoring the number of
[2976.440-2977.630] months that sort of like open-source
[2977.640-2979.750] models are behind. Um And started with
[2979.760-2981.390] there's nothing and then it went to 18
[2981.400-2981.870] months. Now it's
[2981.880-2983.830] &gt;&gt; Yeah, but then convergence, right? So
[2983.840-2985.150] then maybe they're behind by like, what
[2985.160-2986.590] is the latest? Maybe like 8 months, 6
[2986.600-2987.670] months, 8 months kind of thing right
[2987.680-2988.750] now. Yeah, I'm a huge fan of
[2988.760-2990.150] open-source, obviously. So for example,
[2990.160-2991.270] in operating systems, you have like
[2991.280-2992.590] closed source, like, you know, Windows
[2992.600-2994.030] and Mac OS, these are large software
[2994.040-2995.310] projects, kind of like what LLMs are
[2995.320-2997.190] going to become, and there's Linux. Mhm.
[2997.200-2999.150] But Linux is very easy. Like, actually
[2999.160-3000.510] Linux is extremely successful project.
[3000.520-3001.590] It runs on the vast majority of
[3001.600-3003.310] computers. Like, last time I checked,
[3003.320-3005.390] was it like 60% or something like from
[3005.400-3007.790] Linux? Um and that's because there is a
[3007.800-3009.630] need in the industry to have a common
[3009.640-3011.590] open platform that everyone feels uh
[3011.600-3013.390] sort of safe using. I would say like the
[3013.400-3014.830] industry has always felt a demand for
[3014.840-3016.590] that kind of a project to exist. Mhm.
[3016.600-3018.110] &gt;&gt; And I think the same is true now. And
[3018.120-3019.230] that's why businesses actually want
[3019.240-3021.470] there's demand for this kind of a um a
[3021.480-3023.190] thing to exist. The big difference is
[3023.200-3025.230] that everything is capital uh there's a
[3025.240-3027.310] lot of capex that goes into this.
[3027.320-3029.470] &gt;&gt; Um so I think that's where things like
[3029.480-3030.550] fall apart a little bit, make it a bit
[3030.560-3032.630] harder to to compete in certain senses.
[3032.640-3033.830] Uh I I do think that the current models
[3033.840-3035.070] are very good. The other thing that I
[3035.080-3036.830] think is like really interesting is that
[3036.840-3038.150] for the vast majority of like consumer
[3038.160-3039.790] use cases and things like that, even
[3039.800-3041.190] like turn open-source models are
[3041.200-3042.950] actually quite good, I would say. And I
[3042.960-3045.630] think like if you go forward like more
[3045.640-3047.870] uh more years, it does seem to me like a
[3047.880-3050.510] huge amount of like simple use cases are
[3050.520-3051.750] going to be well covered and actually
[3051.760-3054.190] even run locally. Mhm. Um
[3054.200-3055.390] but there's going to be always like some
[3055.400-3056.950] demand for like frontier intelligence
[3056.960-3058.310] and that that can actually be extremely
[3058.320-3060.150] large uh piece of the pie. But it could
[3060.160-3061.430] be that the frontier the need for
[3061.440-3062.630] frontier intelligence is going to be
[3062.640-3064.670] like, you know, Nobel Prize kind of
[3064.680-3065.790] work. Mhm.
[3065.800-3068.310] &gt;&gt; let's move Linux from C to Rust. It's
[3068.320-3069.950] going to be like bigger projects, you
[3069.960-3072.190] know, like scoped in that kind of a way,
[3072.200-3074.790] and there's going to be maybe more um
[3074.800-3075.870] and maybe that's where a lot of the
[3075.880-3077.630] frontier closed intelligence is where
[3077.640-3078.750] going to are going to be interacting
[3078.760-3080.830] with. And open-source kind of like going
[3080.840-3082.470] to eat through a lot of the more basic
[3082.480-3084.230] use cases or something like that. You
[3084.240-3085.670] know, at some point what is frontier
[3085.680-3087.630] today is going to be, you know, probably
[3087.640-3089.470] later this year what's frontier today in
[3089.480-3090.950] terms of what I'm using right now from
[3090.960-3093.150] the closed labs uh might be open-source
[3093.160-3094.070] and that's going to be doing a lot of
[3094.080-3095.190] work. So I kind of expect that this
[3095.200-3096.070] dynamic will actually basically
[3096.080-3097.990] continue. Like we'll have frontier labs
[3098.000-3099.990] that have closed um AIs that are kind of
[3100.000-3101.470] like these oracles, and then we'll have
[3101.480-3102.670] open-source kind of like behind with
[3102.680-3104.310] some amount of months. And I kind of
[3104.320-3106.990] expect that to uh to continue. And I
[3107.000-3107.990] actually think that's like a pretty
[3108.000-3111.510] pretty good setup uh overall. Um
[3111.520-3113.190] because I I'm a little bit hesitant of
[3113.200-3114.790] having um I don't actually think it's
[3114.800-3116.510] like structurally I think there's some
[3116.520-3118.190] systemic risk attached to just having
[3118.200-3119.590] intelligence that are closed and that's
[3119.600-3122.070] like that's it. Mhm. And I think that
[3122.080-3123.590] that's a, you know, centralization has a
[3123.600-3125.750] very poor track record in my view uh in
[3125.760-3127.590] in the past and has um
[3127.600-3129.590] &gt;&gt; You mean like in political or economic
[3129.600-3130.926] systems in in general.
[3130.936-3132.270] &gt;&gt; [laughter]
[3132.280-3133.510] &gt;&gt; Exactly. I think there's like a lot of
[3133.520-3133.910] like pretty
[3133.920-3135.990] &gt;&gt; an Eastern European. A lot of pretty bad
[3136.000-3137.270] precedents, so I want there to be a
[3137.280-3138.990] thing that is maybe not at the edge of
[3139.000-3140.190] capability because it's new and
[3140.200-3141.710] unexplored, etc. But I want there to be
[3141.720-3144.110] a thing that's behind and that uh is
[3144.120-3145.550] kind of like a common working space for
[3145.560-3147.150] intelligences that the entire industry
[3147.160-3148.430] has access to. Yeah, that seems to me
[3148.440-3150.110] like a pretty decent power balance for
[3150.120-3151.950] the industry. Yeah. I also think there's
[3151.960-3153.070] just like there are many problems to
[3153.080-3155.470] solve, right? Like if you keep advancing
[3155.480-3157.670] intelligence from the frontier, we can
[3157.680-3159.110] do new things and there are a lot of
[3159.120-3160.910] like very big problems for humanity,
[3160.920-3163.550] right? And so like it seems that that
[3163.560-3164.750] will continue to be a very expensive
[3164.760-3166.390] game. And so I want to like root for
[3166.400-3168.110] labs that are doing that because there
[3168.120-3169.470] are problems we cannot solve without
[3169.480-3171.190] continuing to advance the models in a
[3171.200-3173.430] very expensive way. And yet, as you
[3173.440-3176.670] point out, like if what we have
[3176.680-3179.110] today as frontier is open, that's a lot
[3179.120-3181.430] of capability, right? And and so I I I
[3181.440-3183.030] think, you know, the power of that or
[3183.040-3184.790] the democratization of that seems like
[3184.800-3186.630] &gt;&gt; Yeah. very useful and also healthy.
[3186.640-3188.310] &gt;&gt; Yeah. I think basically by accident
[3188.320-3189.710] we're actually like in an okay spot.
[3189.720-3191.070] &gt;&gt; An optimal. Yeah. [laughter] Yeah. Like
[3191.080-3192.510] by accident we we are it happened to be
[3192.520-3194.510] in a good spot in a certain sense. Mhm.
[3194.520-3196.350] Um Well, and and to some degree the the
[3196.360-3199.470] longer this endures, like this dynamic,
[3199.480-3201.670] um the the the healthier of a spot like
[3201.680-3204.030] the ecosystem might be in, right?
[3204.040-3205.150] Because you have more and more area
[3205.160-3205.910] under the curve.
[3205.920-3206.790] &gt;&gt; Mhm. And I will say that even on the
[3206.800-3208.470] closed side, I I almost feel like it's
[3208.480-3210.070] been like even further centralizing
[3210.080-3211.310] recently because I think a lot of the
[3211.320-3212.790] frontrunners are like not necessarily
[3212.800-3215.990] like the top tier. And so uh yeah, like
[3216.000-3217.790] in that sense I think it's um it's not
[3217.800-3219.710] super ideal. I would love there to be
[3219.720-3220.950] more
[3220.960-3222.190] more frontier labs because yeah, I'm
[3222.200-3224.510] like by default very suspicious of like
[3224.520-3225.750] um
[3225.760-3226.670] I want there to be more people in the
[3226.680-3228.270] room. I want I think like in machine
[3228.280-3230.030] learning ensembles always outperform any
[3230.040-3231.830] individual model. And so I want there to
[3231.840-3233.510] be ensembles of people thinking about
[3233.520-3234.630] all the hardest problems and I want
[3234.640-3236.030] there to be ensembles of people in the
[3236.040-3237.590] room when they um
[3237.600-3239.150] to be all well informed and to make
[3239.160-3241.190] those decisions, you know, so uh I don't
[3241.200-3242.390] want it to be like a closed doors with
[3242.400-3243.750] two people or three people. I feel like
[3243.760-3245.590] that's like not a good not a good
[3245.600-3246.990] future. I almost wish like there were
[3247.000-3248.430] more labs as long as they're short and I
[3248.440-3250.790] I I do think that open-source has a has
[3250.800-3251.510] a
[3251.520-3253.150] has a place to play. I hope it sticks
[3253.160-3255.590] around and I basically I it's currently
[3255.600-3257.030] slightly behind and it's actually kind
[3257.040-3259.070] of like a good thing. Okay, you worked
[3259.080-3261.470] on the precursor to generalized robotics
[3261.480-3264.430] autonomy um in cars, right?
[3264.440-3267.190] Uh a a lot has happened in the last
[3267.200-3269.310] couple months with robotics companies as
[3269.320-3271.550] well, like acceleration of really
[3271.560-3273.670] impressive generalization of
[3273.680-3275.790] environment, of tasks, like increasingly
[3275.800-3277.270] long horizon tasks, lots of money going
[3277.280-3279.030] into the space. Like, is it going to
[3279.040-3280.910] happen? Has anything in your view
[3280.920-3283.230] changed recently? Uh so like my view is
[3283.240-3284.349] kind of informed by what I saw in
[3284.359-3285.390] self-driving and I do feel like
[3285.400-3286.550] self-driving is the first robotics
[3286.560-3288.470] application. So probably what I saw is
[3288.480-3289.990] at the time, like 10 years ago, there
[3290.000-3291.910] were a large number of startups. And I
[3291.920-3293.630] kind of feel like um
[3293.640-3295.310] like most of them basically like didn't
[3295.320-3297.710] long-term make it. Um and what I saw is
[3297.720-3299.230] that like a lot of capital expenditure
[3299.240-3301.950] had to go in and a lot of time. And so
[3301.960-3303.830] um I think it's like I think robotics,
[3303.840-3305.910] because it's so difficult, is so messy,
[3305.920-3306.990] and requires a huge amount of capital
[3307.000-3308.510] investment, and a lot of like
[3308.520-3309.710] conviction.
[3309.720-3311.990] Um just it's like a big problem and I
[3312.000-3313.870] think atoms are really hard. So I kind
[3313.880-3315.230] of feel like they will lag be it will
[3315.240-3316.349] lag behind what's going to happen in
[3316.359-3317.910] digital space. And in digital space
[3317.920-3319.070] there's going to be a huge amount of
[3319.080-3321.349] unhobbling, uh basically like things
[3321.359-3323.150] that weren't super efficient becoming a
[3323.160-3324.670] lot more efficient by like a factor of a
[3324.680-3325.230] hundred.
[3325.240-3327.230] &gt;&gt; Mhm. Because bits are so much easier.
[3327.240-3329.470] And so I think currently in terms of
[3329.480-3331.349] what's going to change and
[3331.359-3333.110] like where the activity is, I kind of
[3333.120-3335.110] feel like digital space is going to like
[3335.120-3336.830] change a huge amount. And then the
[3336.840-3338.270] physical space will lag behind. And what
[3338.280-3339.630] I find very interesting is like this
[3339.640-3341.270] interface in between them as well.
[3341.280-3343.390] Because I think in this like if you we
[3343.400-3345.070] do have more agents acting on behalf of
[3345.080-3346.710] humans and more agents kind of like
[3346.720-3348.870] talking to each other and and doing
[3348.880-3350.510] tasks and participating in kind of
[3350.520-3353.150] economy of agents, etc. Um you're going
[3353.160-3354.349] to run out of things that you're going
[3354.359-3356.270] to do purely in the digital space. At
[3356.280-3357.230] some point you have to go to the
[3357.240-3358.110] universe and you have to ask it
[3358.120-3360.390] questions. Um you have to run an
[3360.400-3361.550] experiment and see what the universe
[3361.560-3362.750] tells you to get back to learn
[3362.760-3365.390] something. And so we currently have a
[3365.400-3367.150] huge amount of like digital work uh
[3367.160-3368.670] because there's an overhang in how much
[3368.680-3370.830] we collectively thought about what
[3370.840-3372.230] already is digital.
[3372.240-3373.270] So we just didn't have enough thinking
[3373.280-3374.630] cycles among the humans to think about
[3374.640-3375.790] all the information that is already
[3375.800-3378.550] digital and already uploaded. Um and so
[3378.560-3379.470] we're going to start running out of
[3379.480-3381.910] stuff that is actually like um
[3381.920-3383.950] already up uploaded. Uh so you're going
[3383.960-3385.150] to at some point read all the papers and
[3385.160-3386.670] process them and have some ideas about
[3386.680-3388.990] what to try, but um yeah, we're just
[3389.000-3389.710] going to
[3389.720-3391.110] uh I don't actually know how much you
[3391.120-3392.590] can like get intelligence that's like
[3392.600-3393.950] fully closed off and was just
[3393.960-3395.270] information that's available in the you
[3395.280-3396.870] know. And so I think what's going to
[3396.880-3398.030] happen is first there's going to be a
[3398.040-3399.110] huge amount of unhobbling and I think
[3399.120-3400.310] there's a huge amount of work there.
[3400.320-3401.470] Then actually it's going to move to like
[3401.480-3402.750] the interfaces between physical and
[3402.760-3405.710] digital. So I and that's like sensors of
[3405.720-3407.230] like seeing the world and actuators of
[3407.240-3408.390] like doing something to the world.
[3408.400-3409.470] &gt;&gt; Mhm. So I think a lot of interesting
[3409.480-3411.550] companies will actually come from that
[3411.560-3413.910] interface of like can we feed the
[3413.920-3415.950] superintelligence in a certain sense uh
[3415.960-3417.870] data and can we actually like take data
[3417.880-3420.190] out and manipulate the physical world um
[3420.200-3421.710] per its bidding if you want to like
[3421.720-3423.270] anthropomorphize the whole thing, right?
[3423.280-3424.790] And then the the physical world actually
[3424.800-3426.230] I almost feel like the the total
[3426.240-3427.750] addressable market, etc. in terms of
[3427.760-3429.430] like the amount of work and so on is is
[3429.440-3431.910] massive, possibly even much larger maybe
[3431.920-3433.550] what can happen in digital space. So
[3433.560-3434.670] actually think it's like a much bigger
[3434.680-3438.030] opportunity as well. But um
[3438.040-3439.030] I do feel like it's a huge amount of
[3439.040-3441.910] work and and in my in my mind the atoms
[3441.920-3444.030] are just like a a million times harder.
[3444.040-3446.510] So um so it will lag behind, but it's
[3446.520-3447.910] also I think a little bit of a bigger
[3447.920-3449.950] market. So it's kind of like uh yeah, I
[3449.960-3451.230] think the opportunity is kind of like
[3451.240-3452.950] follow that kind of trajectory. So right
[3452.960-3456.190] now is digital is like my main interest.
[3456.200-3458.190] Then interfaces will be like after that
[3458.200-3459.830] and then maybe like some of the physical
[3459.840-3461.790] things um like their time will come and
[3461.800-3463.830] they'll be huge when they do come.
[3463.840-3464.950] Well, it's it's it's an interesting
[3464.960-3466.590] framework for it, too, because uh
[3466.600-3467.630] certain things, not the things I'm
[3467.640-3468.710] working on right now, but certain things
[3468.720-3470.630] are much easier even in the world of
[3470.640-3471.150] atoms.
[3471.160-3472.950] &gt;&gt; Mhm. Right? Like if you just think about
[3472.960-3474.630] like read and write to the physical
[3474.640-3477.230] world, like read, like sensors, cameras,
[3477.240-3478.830] like there's a lot of existing hardware
[3478.840-3480.990] and you can imagine like
[3481.000-3483.190] enriching agent capabilities or
[3483.200-3484.790] capturing a lot of new data if you just
[3484.800-3486.430] clever about it and like you don't
[3486.440-3489.110] necessarily have to invest a lot to like
[3489.120-3490.270] get something valuable.
[3490.280-3492.230] &gt;&gt; Yeah. Right. Yeah. So like examples of
[3492.240-3493.590] this that I saw for example are, you
[3493.600-3495.750] know, um a friend of mine, Liam, is
[3495.760-3498.310] running is a CEO of Periodic. I
[3498.320-3499.750] visited them last week. Yeah. So it was
[3499.760-3501.230] just on top of mind. Like they're trying
[3501.240-3502.830] to do auto research for materials
[3502.840-3504.670] science. Mhm. Um and so in that case
[3504.680-3505.990] it's like the sensors to the
[3506.000-3507.270] intelligence are actually like pretty
[3507.280-3509.150] expensive lab equipment. And the same is
[3509.160-3510.550] true in biology. I think a lot of people
[3510.560-3511.590] are very interested in engineering
[3511.600-3513.270] biology and, you know, the sensors will
[3513.280-3514.870] be more than just like video cameras.
[3514.880-3516.110] Does that make sense? And then the other
[3516.120-3517.190] thing I was I saw for example is
[3517.200-3519.550] companies that are trying to have um
[3519.560-3520.630] like you basically pay people for
[3520.640-3522.270] training data. Yeah. Yeah. Yeah. Yeah.
[3522.280-3522.830] &gt;&gt; To feed the Yeah.
[3522.840-3523.349] &gt;&gt; programmatically.
[3523.359-3526.550] &gt;&gt; Yeah. To feed to feed the Borg. Uh
[3526.560-3528.870] um and so like these are all examples of
[3528.880-3530.230] like sensors in a certain sense. So they
[3530.240-3531.630] take many diverse shapes and forms if
[3531.640-3533.470] that makes sense. Mhm. Yeah, so I'm
[3533.480-3534.910] looking forward to the point where I can
[3534.920-3537.470] ask for a task in the physical world and
[3537.480-3538.990] I can put a price on it and just tell
[3539.000-3540.710] the agent like, you know, you figure out
[3540.720-3542.310] how to do it. Go get the data.
[3542.320-3543.230] &gt;&gt; I'm actually kind of surprised we don't
[3543.240-3544.990] have enough like information markets.
[3545.000-3546.870] Mhm. Like if for example if Polymarket
[3546.880-3548.190] or other betting markets or even stocks,
[3548.200-3549.910] etc. If they have so much autonomous
[3549.920-3551.510] activity and rising amount of activity,
[3551.520-3553.070] Mhm. like um
[3553.080-3554.630] why should like for example if Iran was
[3554.640-3556.430] just happening now, like how come there
[3556.440-3557.670] isn't a process where like taking a
[3557.680-3559.430] photo or video from somewhere in Tehran
[3559.440-3561.310] should cost like 10 bucks? Like someone
[3561.320-3562.310] should be able to pay for that, you
[3562.320-3563.670] know, like and that's an example of like
[3563.680-3565.270] feeding the intelligence. There's not
[3565.280-3566.390] going to be a human looking at it, it's
[3566.400-3567.670] going to be like agents who are trying
[3567.680-3569.230] to guess the betting games and stock
[3569.240-3570.990] markets and so on. Mhm. So I kind of
[3571.000-3572.430] feel like the agentic web is still like
[3572.440-3573.990] fairly new, but there's no like
[3574.000-3575.190] mechanisms for this, but this is an
[3575.200-3577.870] example of what I I think might happen.
[3577.880-3579.550] Uh there's a good book that maybe is
[3579.560-3581.870] inspiring called Daemon. Mhm. You
[3581.880-3583.830] potentially read it. In Daemon, the
[3583.840-3585.510] intelligence um
[3585.520-3586.950] ends up like puppeteering almost a
[3586.960-3588.150] little bit like humanity in a certain
[3588.160-3589.550] sense, you know? And so, humans are kind
[3589.560-3591.350] of like it's actuators, but humans are
[3591.360-3593.910] also like its sensors. Um and so, I
[3593.920-3595.630] think like collectively like society
[3595.640-3596.950] will kind of like reshape in a certain
[3596.960-3598.630] way in uh
[3598.640-3601.230] to to serve that kind of a
[3601.240-3602.430] that will kind of like end up happening
[3602.440-3604.790] collectively across the industry. Where
[3604.800-3606.550] yeah, there's just a lot more automation
[3606.560-3607.950] and it has certain needs and kind of
[3607.960-3609.870] humans will be serving those needs of
[3609.880-3611.510] that of that machine, not necessarily
[3611.520-3612.230] like to each other.
[3612.240-3614.230] &gt;&gt; Well, we were um on this very specific
[3614.240-3616.830] point of uh like missing pieces of
[3616.840-3618.310] training data. We needed um we needed
[3618.320-3619.750] something like auto research, right?
[3619.760-3621.550] Like we we need the training cycle or
[3621.560-3624.550] the SFTP piece to be uh
[3624.560-3627.950] far more mechanized. Mhm. For for which
[3627.960-3628.270] part?
[3628.280-3630.390] &gt;&gt; In order to make the
[3630.400-3632.270] uh collection like to in order to take
[3632.280-3633.870] the human out of the loop to ask for a
[3633.880-3635.550] task that is just like improve my model
[3635.560-3640.070] quality with new data, right? Uh yes.
[3640.080-3642.550] Does that make sense to you? Like we um
[3642.560-3644.830] if you can't have the model do the
[3644.840-3648.510] training runs by itself, then your
[3648.520-3650.910] ability to do this as a like closed loop
[3650.920-3654.830] task with uh by pricing data is um more
[3654.840-3657.190] challenged. Yes, yes, 100%. Yeah. But
[3657.200-3657.710] now you do.
[3657.720-3659.430] &gt;&gt; The thing is for LLM training, it
[3659.440-3661.070] actually is like very easily it like
[3661.080-3663.510] really fits the paradigm. Mhm. Um so,
[3663.520-3664.430] you'd actually expect
[3664.440-3666.430] &gt;&gt; metric. Yeah, like LLM training actually
[3666.440-3667.670] fits the paradigm really well, really
[3667.680-3669.470] easily. Like all the optimization of all
[3669.480-3671.190] the code and so, it runs faster. And
[3671.200-3672.750] then you also have like metrics that you
[3672.760-3674.590] can optimize against. I do think that if
[3674.600-3676.070] you had an autonomous loop over those
[3676.080-3677.310] metrics, there's going to be a lot of
[3677.320-3678.870] like good herding going on where the
[3678.880-3679.990] system will like overfit to those
[3680.000-3682.510] metrics. And so, um but then you can use
[3682.520-3683.870] the system to devise more metrics and
[3683.880-3685.510] you just have a really good coverage.
[3685.520-3688.150] So, it's kind of hard to tell, but um
[3688.160-3689.230] in a certain sense it's like a pretty
[3689.240-3691.310] pretty good fit. I want to talk about a
[3691.320-3692.630] little uh
[3692.640-3694.150] tiny side project you have before we
[3694.160-3696.430] end. Um tell me about the micro GPT
[3696.440-3697.830] arts. Oh, yeah.
[3697.840-3700.070] Okay, so micro GPT. So, I have this like
[3700.080-3701.870] running obsession of like maybe a decade
[3701.880-3703.350] or two of just like simplifying and
[3703.360-3706.590] boiling down the uh basically LLMs uh to
[3706.600-3708.350] like their bare essence. And I've had a
[3708.360-3709.990] number of projects along these lines.
[3710.000-3713.670] So, like nano GPT and um make more and
[3713.680-3716.630] uh micro GPT micro grad etc. So, I feel
[3716.640-3718.030] like micro GPT is now the state of the
[3718.040-3719.550] art of me trying to like just boil it
[3719.560-3721.470] down to just the essence. Because the
[3721.480-3723.390] thing is like training neural nets and
[3723.400-3725.630] LLMs specifically um is a huge amount of
[3725.640-3727.510] code, but all of that code is actually
[3727.520-3729.670] complexity from efficiency. It's just
[3729.680-3731.230] because you need it to go fast. If you
[3731.240-3732.550] don't need it to go fast and you just
[3732.560-3734.150] care about the algorithm, then that
[3734.160-3735.790] algorithm actually is uh 200 lines of
[3735.800-3737.790] Python, very simple to read. And this
[3737.800-3739.910] includes comments and everything. Um
[3739.920-3741.470] because you just have like uh your data
[3741.480-3743.750] set which is a text um and you need your
[3743.760-3744.910] neural network architecture which is
[3744.920-3746.390] like 50 lines. You need to do your
[3746.400-3748.190] forward pass and then you have to do
[3748.200-3749.310] your backward pass to calculate the
[3749.320-3751.790] gradients. And so, an auto grad engine
[3751.800-3753.110] uh to calculate the gradients like 100
[3753.120-3754.830] lines. And then you need an optimizer
[3754.840-3756.870] and Adam for example, uh which is a very
[3756.880-3758.230] state of the art optimizer is like again
[3758.240-3760.510] 10 lines, really. And so, putting
[3760.520-3761.830] everything together in the training loop
[3761.840-3764.350] is like yeah, 200 lines. And what's
[3764.360-3766.830] interesting to me like normally before
[3766.840-3769.110] like maybe a year ago or more, if I had
[3769.120-3770.390] come up with micro GPT, I would be
[3770.400-3772.110] tempted to basically explain to people.
[3772.120-3774.710] Like I have a video like stepping
[3774.720-3776.470] through it or something like that. Uh
[3776.480-3777.910] and I actually tried to make that video
[3777.920-3779.430] a little bit. And I tried to make like a
[3779.440-3781.190] little guide to it and so on. But I kind
[3781.200-3783.550] of realized that this is is not really
[3783.560-3785.030] is not really adding too much because
[3785.040-3786.830] people cuz it's already so simple that
[3786.840-3788.150] it's 200 lines that anyone could ask
[3788.160-3789.830] their agent to explain it in various
[3789.840-3791.870] ways. And the agents like I'm not
[3791.880-3792.990] explaining to people anymore. I'm
[3793.000-3794.710] explaining it to agents. If you can
[3794.720-3796.670] explain it to agents, then agents can be
[3796.680-3798.350] the router and they can actually target
[3798.360-3800.790] it to the human in their language uh
[3800.800-3802.670] with infinite uh you know,
[3802.680-3805.230] patience and uh just at their capability
[3805.240-3807.310] and so on. Right. If I don't understand
[3807.320-3809.990] um this particular function, I can ask
[3810.000-3811.150] the agent to explain it to me like three
[3811.160-3812.470] different ways and I'm not going to get
[3812.480-3814.310] that from you. Exactly. And so, I kind
[3814.320-3814.990] of feel like, you know, what is
[3815.000-3816.670] education? Like it used to be guides, it
[3816.680-3818.070] used to be lectures, it used to be this
[3818.080-3819.830] thing, but now I feel like now more I'm
[3819.840-3821.430] explaining things to agents and maybe
[3821.440-3824.310] I'm coming up with skills uh where like
[3824.320-3825.270] um
[3825.280-3827.470] uh so, basically skill is just a way to
[3827.480-3828.950] instruct the agent how to teach the
[3828.960-3830.590] thing. So, maybe I could have a skill
[3830.600-3832.310] for micro GPT of the progression I
[3832.320-3833.510] imagine the agent should take you
[3833.520-3834.390] through if you're interested in
[3834.400-3836.070] understanding the code base. And it's
[3836.080-3838.150] just like hints to the model to like uh
[3838.160-3839.349] first start off with this and then with
[3839.359-3841.310] that. And so, I could just script the
[3841.320-3843.230] curriculum a little bit as a skill.
[3843.240-3844.510] Uh so,
[3844.520-3846.750] uh so, I I don't feel like um
[3846.760-3847.710] yeah, I feel like there's going to be
[3847.720-3849.550] less of like explaining things directly
[3849.560-3850.790] to people and it's going to be more of
[3850.800-3852.870] just like does the agent get it? And if
[3852.880-3853.790] the agent gets it, they'll do the
[3853.800-3856.110] explanation. And we're not fully there
[3856.120-3857.950] yet because they I still can I still
[3857.960-3859.230] think I can probably explain things a
[3859.240-3860.670] little bit better than the agents, but I
[3860.680-3861.870] still feel like the models are improving
[3861.880-3864.710] so rapidly that um
[3864.720-3866.230] I feel like it's a losing battle to some
[3866.240-3868.150] to some extent.
[3868.160-3870.510] Um and so, I think education is going to
[3870.520-3871.990] be kind of like reshuffled by this quite
[3872.000-3874.670] substantially uh where it's the end of
[3874.680-3876.470] like teaching each other things a little
[3876.480-3879.110] bit like if I have a um library for
[3879.120-3880.670] example of code or something like that.
[3880.680-3881.430] It used to be that you have
[3881.440-3882.790] documentation for other people who are
[3882.800-3884.110] going to use your library, but like you
[3884.120-3885.230] shouldn't do that anymore. Like you
[3885.240-3887.030] should have instead of HTML documents
[3887.040-3888.349] for humans, you have markdown documents
[3888.359-3890.670] for agents. Cuz if agents get it, then
[3890.680-3891.790] they can just explain all the different
[3891.800-3894.270] parts of it. So, it's this redirection
[3894.280-3895.750] through agents, you know?
[3895.760-3897.910] Um and that's why. So, I think we're
[3897.920-3899.630] going to see a lot more of that playing
[3899.640-3901.430] out. Well, we'll see if the great
[3901.440-3903.750] teachers know like to develop intuition
[3903.760-3905.230] for how to explain things to agents
[3905.240-3905.870] differently.
[3905.880-3907.550] &gt;&gt; ultimately, so for example, micro GPT,
[3907.560-3909.710] like I asked I tried to get an agent to
[3909.720-3911.510] write micro GPT. So, I told it like try
[3911.520-3914.230] to boil down the simplest things. Like
[3914.240-3916.070] try to boil down my um neural network
[3916.080-3916.910] training to the simplest thing and it
[3916.920-3920.030] can't do it. Like micro GPT is like my
[3920.040-3922.590] is it's like my end of my obsession.
[3922.600-3924.830] It's the 200 lines. I thought about this
[3924.840-3926.070] for a long time. I was obsessed about
[3926.080-3927.590] this for a long time. This is this is
[3927.600-3929.510] the solution. Trust me, it can't get
[3929.520-3931.710] simpler. And this is this is my value
[3931.720-3933.670] add. Everything else like agent gets it.
[3933.680-3934.830] It just can't come up with it, but it
[3934.840-3936.670] totally gets it and understands why it's
[3936.680-3938.790] done in a certain way etc. Uh so, like
[3938.800-3940.150] my contribution is kind of like these
[3940.160-3942.110] few bits, but everything else in terms
[3942.120-3944.510] of like the education that goes on after
[3944.520-3947.070] that is like not my domain anymore.
[3947.080-3948.310] So, maybe
[3948.320-3949.550] yeah, it's like education kind of
[3949.560-3950.790] changes in those ways where you kind of
[3950.800-3952.150] have to infuse the few bits that you
[3952.160-3954.630] feel strongly about the curriculum or
[3954.640-3956.270] the the best the better way of
[3956.280-3957.270] explaining it or something like that.
[3957.280-3958.910] The things that agents can't do is your
[3958.920-3961.630] job now. The things that agents can do,
[3961.640-3962.950] they can probably do better than you or
[3962.960-3965.750] like very soon. And so, you should um be
[3965.760-3966.950] strategic about what you're actually
[3966.960-3968.430] spending time on. Well, we appreciate
[3968.440-3969.590] the few bits.
[3969.600-3970.830] Thank you, Andre.
[3970.840-3973.390] Okay.
[3975.885-3975.895] Find us on Twitter at No Priors Pod.
[3975.895-3975.950] &gt;&gt; [music]
[3975.960-3977.670] &gt;&gt; Subscribe to our YouTube channel if you
[3977.680-3979.670] want to see our faces. Follow the show
[3979.680-3982.030] on Apple Podcasts, Spotify, or wherever
[3982.040-3983.150] you listen. [music] That way you get a
[3983.160-3985.230] new episode every week. And sign up for
[3985.240-3986.910] emails or find transcripts for every
[3986.920-3990.800] episode at no-priors.com.
