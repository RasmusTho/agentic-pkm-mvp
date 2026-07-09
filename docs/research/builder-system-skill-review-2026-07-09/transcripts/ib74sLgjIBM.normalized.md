# Transcript: Build A Claude Knowledge Base That Self-Improves!

State: Supporting evidence transcript (advisory research corpus)

- Video ID: `ib74sLgjIBM`
- URL: https://youtu.be/ib74sLgjIBM?si=ZX21BURpRjH2fEyb
- Channel: Systems Made Better
- Publish date: 20260523
- Duration seconds: 2175
- Metadata language: `en`
- Caption language: `en`
- Acquisition method: `captions_auto`
- Selection path: `pipeline_selector`
- Quality note: machine-generated auto-captions; rolling-cue duplication removed by normalization, punctuation/segmentation may still be imprecise
- Content identity: `sha256:b14b7aeb6e3e5c32e9340c1dde08fbfb3dd94922df55e3626c63f35f41c084fc`

## Chapters

- 0.0: Build Karpathy's AI Knowledge Base in Claude
- 116.0: My Claude CoWork Knowledge Base: System Overview
- 236.0: The Claude Build - System Setup
- 680.0: The Claude Build - Information Dump
- 968.0: The Claude Build - Create the Wiki
- 1237.0: Creating A Compounding Loop: Self-Improvement in Claude
- 1462.0: System Health Check: Claude CoWork Scheduled Task
- 2019.0: Final Results
- 2093.0: The 1 Day vs 100 Day Transformation To Aim For

## Normalized Transcript

[2.350-2.360] For years, I've used a second brain.
[2.360-4.270] This might be the simplest, most
[4.280-6.510] powerful self-learning personal
[6.520-8.350] knowledge base I've ever discovered
[8.360-9.990] built with Claude, and I'm going to show
[10.000-11.710] you how to do it. Hi, at the start of
[11.720-14.550] 2026, one of the most respected voices
[14.560-17.550] in AI quietly posted how he runs his own
[17.560-19.670] personal knowledge base, a second brain
[19.680-20.950] where you hold all your information and
[20.960-23.030] make connections and use it to inform
[23.040-26.110] what you do. 105,000 people bookmarked
[26.120-27.990] it, and probably almost none of them
[28.000-29.830] have built one. And that's the problem.
[29.840-32.269] This is genuinely the most useful AI
[32.279-34.590] setup I've seen in months and
[34.600-37.030] implemented in Claude, and it takes
[37.040-39.550] probably 45 minutes to build over a
[39.560-41.790] weekend. No Obsidian, no vector
[41.800-44.590] databases, no code, just a brilliant
[44.600-46.870] self-improving knowledge base. Here's
[46.880-48.830] exactly what you're getting in this
[48.840-50.350] video. I'm going to show you the
[50.360-53.030] architecture, the whole system in 60
[53.040-54.590] seconds. I'm going to show you the
[54.600-56.670] framework of how to build it and build
[56.680-59.270] it with you right now on this video. And
[59.280-60.790] then, I'm going to show you the Claude
[60.800-63.910] skill that helps you audit it and help
[63.920-66.190] it improve and maintain itself over
[66.200-69.230] time. The five-step framework is this:
[69.240-72.150] you set it up, you dump your information
[72.160-74.590] into it, you then get AI to build a
[74.600-76.830] wiki, you ask it questions and create a
[76.840-79.150] compounding link to save answers back
[79.160-80.750] into it, and with a health check and
[80.760-82.990] that loop, it just keeps improving over
[83.000-84.870] time. So, by the end of this video,
[84.880-86.630] you'll know exactly what the system is,
[86.640-89.350] why it beats every Obsidian plus plugins
[89.360-92.150] setup you can find for simplicity, and
[92.160-93.830] how to build your own right now with
[93.840-95.590] Claude. Now, I found that day one of
[95.600-96.750] running it, your knowledge base is
[96.760-99.270] pretty basic, but day 100, it's a
[99.280-101.910] company asset that nobody else has. Your
[101.920-104.550] perspective, your sources, your judgment
[104.560-106.470] in one place. So, double-check you're
[106.480-108.230] actually subscribed to Systems Made
[108.240-110.270] Better right now, cuz YouTube might just
[110.280-111.870] be feeding you this anyway, and let's
[111.880-113.790] get on with all becoming significantly
[113.800-119.870] more intelligent very quickly.
[122.110-122.120] So, here's the top-level design in just
[122.120-124.590] 60 seconds before we go ahead and build
[124.600-126.390] it. Essentially, you're looking at three
[126.400-129.109] folders and one file on your computer
[129.119-131.510] that Claude looks at. I'm putting this
[131.520-134.230] right inside my Coda OS and I'm going to
[134.240-136.550] be adding it to the template system
[136.560-139.230] soon. You've got a Claude MD at the top
[139.240-140.590] of the knowledge base, which is the
[140.600-142.710] schema. It directs Claude on how to read
[142.720-144.350] it and use it. You've then got three
[144.360-146.990] folders. Raw, think of raw as your junk
[147.000-149.070] drawer. Articles, notes, screenshots,
[149.080-150.870] meetings, you just everything goes in
[150.880-152.230] here and you save it and you don't
[152.240-154.110] organize it. Then you've got the wiki
[154.120-156.949] where AI writes the organized version.
[156.959-158.949] You never edit this by hand. It's all
[158.959-160.390] done by the AI. And then you've got
[160.400-163.310] outputs, answers, briefings, and reports
[163.320-165.030] that the AI generates when you ask it
[165.040-167.150] questions. And the best bit is those
[167.160-169.270] then get fed back in and help to refine
[169.280-171.510] it. Plus one file at the root, yeah? The
[171.520-173.870] Claude MD. And you could have multiple
[173.880-175.910] versions of this within essentially a
[175.920-178.190] top-level where it all sits. That means
[178.200-180.150] you can have multiple knowledge bases
[180.160-181.910] all connected together. That's it. No
[181.920-184.509] database, no Obsidian, no vault setup,
[184.519-186.270] just folders and text files on your
[186.280-188.790] computer. And before you ask, no, you
[188.800-191.550] don't need a rag embedding or any vector
[191.560-193.150] store, if you know what all that stuff
[193.160-195.270] is. Kaparthy's own knowledge base is
[195.280-198.630] around 100 articles and 400,000 words
[198.640-200.710] and the LLM handles it fine maintaining
[200.720-202.990] an index and reading what it needs. If
[203.000-205.590] it works for one of the most respected
[205.600-207.550] AI researchers alive, it'll probably
[207.560-209.430] work for your business. The best thing,
[209.440-211.350] like what I've done in my Notion Agent
[211.360-213.990] OS, is you can then point a custom agent
[214.000-215.630] at that knowledge base and it becomes a
[215.640-218.110] specialist agent expert that you can
[218.120-220.710] speak with. It can use the knowledge to
[220.720-223.509] work on problems with you. But that is
[223.519-225.030] for another video on the channel. I'll
[225.040-226.910] be sharing a video soon about how I'm
[226.920-229.229] turning bodies of work from expert
[229.239-231.390] thinkers into personal assistants that
[231.400-233.110] help me on my business. It's totally
[233.120-234.550] wild. And we're doing that in both
[234.560-239.510] Notion and Claude.
[242.230-242.240] Okay, I am doing this in Claude co-work.
[242.240-243.830] We've got a new window open and I'm
[243.840-245.790] pointing it at my main co-work OS
[245.800-247.630] folder. So, basically, I have everything
[247.640-251.030] in one folder on my home, the local,
[251.040-252.270] there's a Claude co-work folder,
[252.280-253.670] everything happens in here. You just
[253.680-254.710] direct it at it and I've got
[254.720-256.470] instructions like about me files and all
[256.480-258.229] of that. But, watch my how to get set up
[258.239-260.270] on co-work first if you want to do that.
[260.280-261.830] But, we're going to add a new folder in
[261.840-264.590] here called knowledge. There it is.
[264.600-266.670] Going to drop it in at the top level.
[266.680-268.390] We're going to go back to Claude and
[268.400-269.950] we're going to set this up. So, I use
[269.960-272.030] WhisperFlow to instruct Claude on what I
[272.040-273.830] want to build, link in the description.
[273.840-275.390] This is what we're going to say. I want
[275.400-277.990] to build a self-improving knowledge base
[278.000-280.390] that you manage as a librarian. Let's
[280.400-283.470] start and make a folder structure inside
[283.480-285.550] the new folder I've added in your Claude
[285.560-288.270] co-work folder called knowledge. Inside
[288.280-291.070] that, I want three subfolders. We want
[291.080-294.670] raw, wiki, and outputs. Plus, drop a
[294.680-298.310] Claude MD file in the root and I'll show
[298.320-300.310] you what is going to go in that in a
[300.320-302.190] moment. And what you could do is give it
[302.200-304.270] context of what you're doing. So, we
[304.280-307.790] could say, "For context, here is Andre
[307.800-310.390] Karpathy's explanation of what we're
[310.400-312.110] about to build." But, we're going to be
[312.120-313.670] doing this locally rather than with
[313.680-316.190] Obsidian. I'm going to use Opus 4.7 cuz
[316.200-317.909] it's intelligent and it'll do the work,
[317.919-319.230] but probably don't need it. And there it
[319.240-321.190] is. It's turned up. It's dropped those
[321.200-322.030] in.
[322.040-324.630] I'm going to just rename this so it's
[324.640-327.190] clearer. We'll call it knowledge base.
[327.200-328.270] It's interesting that it couldn't read
[328.280-330.150] the Twitter thread, but I'll just put it
[330.160-331.430] in here.
[331.440-334.750] Here's the information for you from that
[334.760-336.390] thread. However, I'm going to take you
[336.400-339.630] through step by step what I want.
[339.640-341.430] Now, if we go back and take a look at
[341.440-343.230] the folder, we've got our knowledge
[343.240-344.750] base. Now, what we might want to do at
[344.760-346.710] our top level is create another one,
[346.720-348.470] second brain knowledge, and we could
[348.480-351.430] drop the whole thing inside that. And we
[351.440-353.110] could give it a subject. So, what do we
[353.120-354.910] want this to be on? Why don't we make
[354.920-357.390] this one on productivity? All right,
[357.400-359.430] I've dropped what we just built into
[359.440-361.390] another top level folder, which is
[361.400-363.990] called second brain knowledge, and
[364.000-365.430] that's going to be the top level where
[365.440-368.190] we can create multiple versions of
[368.200-370.070] knowledge bases. So, based on this
[370.080-371.590] information and what we've created,
[371.600-373.510] please create me another Claude MD file
[373.520-377.270] for that folder, which will explain the
[377.280-380.230] basic layout when a new knowledge base
[380.240-383.230] is created in its folder. Second, I've
[383.240-385.110] renamed the knowledge folder to be a
[385.120-386.670] productivity knowledge base, which is
[386.680-388.510] what we're going to do. And here is a
[388.520-391.790] basic template of what I think the
[391.800-393.710] Claude MD file for each knowledge base
[393.720-395.510] should look like, but please make
[395.520-397.710] suggestions and a plan for how we could
[397.720-400.030] make this really strong and improve on
[400.040-400.870] it.
[400.880-402.270] And then what I've got is a little
[402.280-404.070] example of what I think it might look
[404.080-405.710] like. So, something like this. How it's
[405.720-407.510] organized, what it does. So, we're going
[407.520-408.790] to drop that in.
[408.800-410.350] Okay, great. And you can work with
[410.360-412.630] Claude to improve this. So, giving it
[412.640-415.750] that Karpathy example, it said these are
[415.760-417.550] things that we're going to need in your
[417.560-419.510] Claude MD. So, I'm going to add these
[419.520-422.230] in. We want to make it standardized. We
[422.240-425.190] want to know how health checks work and
[425.200-427.310] when and how to ingest stuff. It's got a
[427.320-429.750] plan. Okay, great. I think ultimately we
[429.760-432.110] will set this to be active as a
[432.120-433.630] librarian
[433.640-435.590] or between active and aggressive. I
[435.600-437.550] think I will do this using scheduled
[437.560-439.830] tasks, and we'll set those up in a bit.
[439.840-441.950] But first of all, I think the main job
[441.960-446.230] is to write the basic Claude MD file for
[446.240-448.110] how this is going to work with your best
[448.120-450.510] suggestions to keep it clean and simple,
[450.520-453.350] but powerful and effective. In terms of
[453.360-455.909] ingesting material, this will just be me
[455.919-457.830] doing this manually, but it wouldn't be
[457.840-459.950] unhelpful for us to add the option for
[459.960-462.150] you to work with me and guide me through
[462.160-464.750] it in a process, so you could work that
[464.760-467.310] in to the top level Claude MD. But I
[467.320-469.110] would like to on the first pass of this
[469.120-470.990] knowledge base input a load of stuff,
[471.000-472.470] and then you would build the wiki from
[472.480-473.950] there. So let's just create the first
[473.960-476.510] instructions. And as for monthly health
[476.520-477.950] checks, we'll come to that later in
[477.960-480.310] detail, but this is a basic suggestion
[480.320-481.830] of how this might work. And I'm going to
[481.840-483.390] paste what I've written in, review the
[483.400-484.990] entire wiki directory, flag
[485.000-486.830] contradictions between articles, find
[486.840-489.750] topics mentioned, list claims not backed
[489.760-492.030] by source, etc. Please write your
[492.040-496.310] proposed top level second brain MD and
[496.320-498.350] then knowledge base MD for the
[498.360-499.870] productivity knowledge base example
[499.880-501.790] we're building. So what I'm essentially
[501.800-503.110] asking you to do is based on this
[503.120-506.190] feedback is build me its best version,
[506.200-509.110] and it's informed by that Kapathy
[509.120-512.350] article that we showed it earlier, which
[512.360-513.870] was here. So it's kind of going to
[513.880-515.430] follow this process, and it's now
[515.440-517.670] building what we need. So in the second
[517.680-520.110] brain knowledge base,
[520.120-521.510] we have a top level one. It's a
[521.520-523.750] container for multiple knowledge bases,
[523.760-525.950] and when it creates a new one, we ask it
[525.960-527.750] to do that, and this is how the system
[527.760-528.870] works,
[528.880-531.750] and how they are independent. Nice. And
[531.760-533.630] then the detailed behavior is for each
[533.640-535.510] system. That's great. Then it should be
[535.520-537.750] working on one in here, and now it's
[537.760-539.910] building this for us. So it's suggested
[539.920-541.470] that the top level file would have a
[541.480-544.590] guided ingestion mode to call on. You
[544.600-546.270] can see what it's up to here. Okay, it's
[546.280-548.150] done it, and here we go. Now what I do
[548.160-549.990] want to make sure I've done in my actual
[550.000-552.750] Claude MD, we open this up, the focused
[552.760-555.670] areas. So list three specific themes
[555.680-557.550] this knowledge base will deepen. I'm
[557.560-559.150] going to change that. This knowledge
[559.160-562.590] base is focused on the ethos of doing
[562.600-565.030] less but better, finding a balanced
[565.040-567.790] approach to a greater contribution to
[567.800-569.030] the world,
[569.040-572.030] deeper thinking, and stronger output
[572.040-574.470] whilst managing health, happiness, and
[574.480-577.270] balance in your life. So the themes are
[577.280-580.110] attention and energy management, systems
[580.120-584.150] design, deep work, essentialism, and
[584.160-587.350] effective contributions
[587.360-589.710] through productivity
[589.720-592.510] principles. Now, one question I have is
[592.520-594.390] whether we need a memory file that
[594.400-597.310] simply lists when
[597.320-601.110] the last action was taken so that the
[601.120-603.670] process that's automated knows what is
[603.680-607.030] new in the raw files and what is
[607.040-609.710] already processed.
[609.720-611.030] Good. So, it agrees that we need a
[611.040-612.670] memory to make sure that it knows when
[612.680-614.310] it last processed something and we can
[614.320-616.830] add that in. This is great. We're all
[616.840-618.350] set. Now, of course, you can do all of
[618.360-619.830] this manually, but I really like the
[619.840-622.110] idea of this being quite automated.
[622.120-623.390] Great. It will make that on the first
[623.400-625.470] pass. Excellent. Now, of course, I'm
[625.480-627.630] building this as I go. I'm learning it
[627.640-629.430] as I go, and I will share my final
[629.440-631.670] templated version for this linked below
[631.680-633.270] if you want to try it, but it will be
[633.280-635.350] part of Co-worker OS. So, check that out
[635.360-637.630] after this. So, step one is essentially
[637.640-639.870] that. Build that system out. And so,
[639.880-642.870] what we should now have is a knowledge
[642.880-646.470] base with the MD ready to go, which will
[646.480-649.070] explain how everything works. It It
[649.080-650.910] talks us through the process, the folder
[650.920-654.030] structure, and what the change log MD
[654.040-656.430] will be, doubling as a system's memory.
[656.440-658.230] It talks it through how to do things.
[658.240-659.550] You don't need to worry too much about
[659.560-661.910] that right now. Uh that is the plan, and
[661.920-663.510] you can ask Claude to do it for you.
[663.520-665.190] We've then got our outputs, which will
[665.200-667.070] be things that it creates for me, raw
[667.080-669.510] and wiki. So, next up, we need to do
[669.520-671.790] step two, which is the dump. And I think
[671.800-673.310] this probably, for most people, might
[673.320-674.790] take like 10 minutes just to find
[674.800-676.270] everything they currently have and put
[676.280-678.430] it into the raw folder. Pretty simple.
[678.440-683.510] I'm just going to do that quite quickly.
[685.910-685.920] The issue many people miss about using a
[685.920-687.670] second brain first. Now, if you've spent
[687.680-690.310] any time on Twitter X, you've watched
[690.320-692.950] the same cycle play out a hundred times.
[692.960-695.270] People post a screenshot of their
[695.280-697.950] Obsidian Vault or Notion setup, linked
[697.960-700.310] notes everywhere, graph views, plugins.
[700.320-702.230] People bookmark it, and then you kind of
[702.240-704.470] forget about it. And to be honest, I've
[704.480-706.150] tried this myself. I've built these in
[706.160-708.590] Notion on my computer and everywhere.
[708.600-710.710] This is the simplest way. But this is
[710.720-712.750] the point about a second brain as well.
[712.760-714.750] We find something brilliant, we save it,
[714.760-716.950] and then we lose it. The fix is a second
[716.960-718.750] brain that actually works intelligently
[718.760-721.750] for you. Okay, great. So next I want to
[721.760-724.550] uh ingest and dump all of my current
[724.560-726.910] knowledge on productivity into our first
[726.920-728.830] trial knowledge base, the productivity
[728.840-731.270] knowledge base. To do this, why don't
[731.280-734.670] you find 10 to 20 strong entries in my
[734.680-736.510] knowledge base in Notion, that can be
[736.520-738.230] found here. So what I'm going to do is
[738.240-740.110] jump over to Notion, go into my
[740.120-741.990] knowledge and research, and we've got a
[742.000-744.030] bunch of stuff in here. So I'm just
[744.040-745.910] going to give it the link to this
[745.920-747.510] database. So why don't we actually like
[747.520-749.430] view the entire database and get the
[749.440-751.630] link to it? We'll go back in, paste that
[751.640-753.470] there. I may also attach a couple of
[753.480-755.550] files here for you. So you can of course
[755.560-757.870] also click this and just add files or
[757.880-759.710] entire folders, whatever you want to do,
[759.720-760.990] but we're just going to try this as a
[761.000-762.750] little example. And while that happens,
[762.760-764.630] I'll show you how that's working in
[764.640-767.150] customize in Claude CoWork. We can go to
[767.160-769.870] connectors, and I've connected up
[769.880-771.790] Notion, so it means that it can now go
[771.800-774.750] and action find and draw stuff from it.
[774.760-776.510] So this is just an example, but it's
[776.520-778.910] also worth saying that in my system, I
[778.920-781.350] have an about me section and a context
[781.360-783.790] map. And that context map shows all of
[783.800-787.630] the key databases in Notion which it can
[787.640-789.670] read from. So in many ways, it should
[789.680-791.030] have already known that. I didn't
[791.040-792.470] actually have to show it, but I really
[792.480-794.630] like that approach to have a context
[794.640-797.030] map. I think try to find good examples
[797.040-799.470] of longer-form entries and clippings,
[799.480-801.710] articles, or quotes from books that have
[801.720-804.070] been added, rather than the AI research
[804.080-806.350] sets. Now while it does that, I want to
[806.360-808.310] say something to you. You don't need to
[808.320-810.470] be tidy when you do this. Just copy and
[810.480-812.470] paste articles, notes, screenshots,
[812.480-815.190] meetings, transcripts into raw. You can
[815.200-817.350] even just paste them into the chat and
[817.360-819.870] get the AI to add them for you. Don't
[819.880-821.830] make this pretty. The point is it's a
[821.840-824.750] folder for capture. The organization is
[824.760-826.990] the AI's job, and that is why this is so
[827.000-829.070] nice to do. For example, here's a blog
[829.080-831.590] from Cal Newport on deep working. What I
[831.600-833.390] might do is just literally take all of
[833.400-836.070] that, copy it, and paste it in here.
[836.080-838.390] Please add this from Cal Newport's deep
[838.400-841.510] work post. PS, when we add stuff to the
[841.520-843.630] raw file, you just add this as an MD
[843.640-845.670] file. Images can also be attached into
[845.680-847.190] it from me.
[847.200-849.630] For example, I've got a my PDF here of
[849.640-852.110] how to build a a gigantic business. I'm
[852.120-854.030] just going to take that and drop it into
[854.040-855.270] raw.
[855.280-857.150] PDFs are probably harder to read. I
[857.160-859.070] think the AI has more trouble with that,
[859.080-860.630] but I'm going to put it in as a test.
[860.640-862.310] Great, so it's fetching a bunch of stuff
[862.320-864.350] from Notion as an example here. Now, one
[864.360-866.190] little tip though, if you're doing this
[866.200-868.990] manually, you can use Xcode. It's a free
[869.000-871.510] Mac desktop app. In there, you can
[871.520-873.230] create markdown files. So, I've just
[873.240-876.590] pasted an article into one from Gretchen
[876.600-879.390] Rubin here and added it into the folder.
[879.400-881.190] So, really quickly, you've added
[881.200-882.470] something in. So, if you want to do
[882.480-885.510] that, you just are going to open Xcode.
[885.520-887.950] You're going to do file new from
[887.960-891.270] template, and you just want to find
[891.280-893.870] markdown file. You just select that,
[893.880-896.550] create a new file, and you can name it,
[896.560-898.110] drop it in, and you're you're good to
[898.120-899.829] go, basically. That's how it would work.
[899.839-901.710] So, that'd be a really quick way to
[901.720-904.110] manually add markdown files in. But, for
[904.120-906.030] a lot of people, um you'll probably be
[906.040-907.870] able to just share the information with
[907.880-909.510] Claude and get it put in. That does cost
[909.520-911.590] credits though. So, it's up to you how
[911.600-913.230] you want to do it. If you do choose to
[913.240-915.430] use Obsidian, they have a great web kit
[915.440-917.870] clipper browser extension that converts
[917.880-920.630] any page into a clean markdown file in
[920.640-922.230] one click, and that's free. So, that's
[922.240-923.750] worth checking out. So, here we go.
[923.760-925.350] We've got a bunch of things in here.
[925.360-927.510] We've added them all as markdown files.
[927.520-931.430] We've got the PDF that I added. We've
[931.440-933.950] also got the one I added using Xcode,
[933.960-936.030] similar situation. And you can, of
[936.040-938.350] course, also just go in to your
[938.360-940.870] downloads folder and just drop images
[940.880-943.550] in. So, there's a JPEG there, which is a
[943.560-945.710] nice example of the process that we're
[945.720-948.910] working through by Corey Gamin. Cool.
[948.920-951.310] So, we've got our raw input. Uh my
[951.320-953.990] Claude system also created an ingested
[954.000-956.150] registry. So, it talks about when
[956.160-958.630] everything went in, which is useful.
[958.640-961.350] Okay, step three is build the wiki. This
[961.360-962.990] probably would take you around 30
[963.000-964.950] minutes. You're going to point Claude at
[964.960-971.190] the folder and give it one prompt.
[973.510-973.520] Read everything in raw and compile a
[973.520-976.390] wiki in the wiki folder following the
[976.400-979.230] rules in your Claude MD. Create the
[979.240-982.870] index MD first, then one MD file per
[982.880-985.510] major topic, and link related topics.
[985.520-987.590] And then you basically walk away and let
[987.600-989.950] it do the job. What you come back to is
[989.960-992.750] information organized. Topic pages with
[992.760-994.710] summaries, connections between ideas you
[994.720-996.990] didn't know existed, an index that makes
[997.000-999.230] everything searchable in second. Now,
[999.240-1000.950] the problem with something like Notion
[1000.960-1003.350] or Obsidian to manage a second brain for
[1003.360-1005.470] knowledge like this is that they kind of
[1005.480-1007.310] ask you to be the librarian. You
[1007.320-1009.030] organize things yourself, you make the
[1009.040-1011.470] links, you manage the tags and folders,
[1011.480-1013.230] you configure plugins, all the rest of
[1013.240-1015.230] it, and then it kind of goes by the
[1015.240-1017.430] wayside. What I think Kaparthy has
[1017.440-1019.470] figured out with this approach using
[1019.480-1021.790] LLMs is that the AI becomes the
[1021.800-1024.189] librarian. You dump information in,
[1024.199-1025.870] Claude organizes and links it,
[1025.880-1028.230] summarizes it, and indexes it, and by
[1028.240-1030.750] the end it's learning and improving on
[1030.760-1033.710] its own, helping you actually apply the
[1033.720-1035.790] knowledge to output. Think what this
[1035.800-1038.189] could do for your team, your business,
[1038.199-1040.590] or just your personal output as someone
[1040.600-1042.910] exploring ideas and work. Okay, so it's
[1042.920-1044.670] working through. You'll see it's created
[1044.680-1047.510] a index. It's written foundational
[1047.520-1049.110] articles, and then it's going to do
[1049.120-1051.630] method articles, thematic articles, and
[1051.640-1053.470] then write a questions MD and a change
[1053.480-1055.790] log. Now, one little tip when you get
[1055.800-1058.030] your AI to do this is to make sure that
[1058.040-1062.270] it's read your anti-AI writing style
[1062.280-1064.390] guide. Now, what that actually looks
[1064.400-1067.510] like in my world is a very similar
[1067.520-1069.630] process to what I've done in my
[1069.640-1071.390] Co-worker OS template. I have this
[1071.400-1073.230] templated in there, and it's really a
[1073.240-1076.070] writing rules MD. And this is built on
[1076.080-1078.350] the Wikipedia anti-AI writing style. So,
[1078.360-1080.110] if you look up AI writing style on
[1080.120-1082.310] Wikipedia, paste that into Claude and
[1082.320-1084.030] say, "Create yourself instructions to
[1084.040-1086.190] never do any of this." It just avoids
[1086.200-1087.990] bad writing, essentially. I'm not going
[1088.000-1089.390] to go into it much further than that.
[1089.400-1092.070] But, I've made sure that Claude, as it's
[1092.080-1094.310] writing its wiki, which you can see it's
[1094.320-1095.910] starting to happen here, look. We're
[1095.920-1097.470] getting all these different things. It's
[1097.480-1100.070] doing that using the writing style
[1100.080-1102.350] guide. It's also great to see here, if
[1102.360-1103.830] we just take a little look, there's
[1103.840-1105.630] loads of information going in, but it
[1105.640-1110.030] takes up so little storage. 4 KB, it's
[1110.040-1111.230] nothing.
[1111.240-1113.510] Uh and this is the joy of MD files. So,
[1113.520-1114.670] let's see what it's got to. Now, I
[1114.680-1117.110] suspect you may be aware that this
[1117.120-1118.990] process is quite demanding. In order to
[1119.000-1121.070] pull this off, you are going to probably
[1121.080-1123.230] either need to do it in sessions, or
[1123.240-1125.270] you're going to want to be in Claude on
[1125.280-1128.270] a Max plan like I am. So, if we go and
[1128.280-1129.630] look in settings, let's take a little
[1129.640-1130.910] look. I've been doing other things on
[1130.920-1133.830] here, but under usage, we're 39% into my
[1133.840-1135.910] current session. And actually, great
[1135.920-1138.030] news, Claude recently announced that
[1138.040-1141.470] they are doubling usage limits across
[1141.480-1144.790] sessions and during peak hours. That's
[1144.800-1147.950] not weekly limits, but it is session
[1147.960-1149.710] limits. And you can, of course, turn on
[1149.720-1151.310] extra usage, but I don't recommend it. I
[1151.320-1154.150] just got a free spend, which is nice.
[1154.160-1157.030] Okay, so we have now built our first
[1157.040-1158.830] knowledge base. We've got our top-level
[1158.840-1160.670] knowledge base here. We've got a Claude
[1160.680-1164.310] MD that instructs us how to build
[1164.320-1167.270] knowledge bases and their structure and
[1167.280-1168.750] what they look like, which means that
[1168.760-1170.990] this can be a global knowledge base with
[1171.000-1173.190] lots of individual ones and we've got
[1173.200-1175.190] that. I've actually got a little memory
[1175.200-1178.070] file here, which shows us that I have a
[1178.080-1179.590] place where I keep my projects that I'm
[1179.600-1180.910] working on and this is really just a
[1180.920-1182.910] memory and a project brief brief for
[1182.920-1184.710] building a project knowledge base, so
[1184.720-1185.870] you don't need to worry about that. And
[1185.880-1187.190] then this is what you've built. You've
[1187.200-1189.470] built a project knowledge base. It has a
[1189.480-1191.670] change log with
[1191.680-1193.550] the most recent entries when things have
[1193.560-1196.270] happened and it has the main Claude MD
[1196.280-1198.910] that instructs the system how to work.
[1198.920-1200.230] So when you do this, make sure you
[1200.240-1201.710] download the templates to get you
[1201.720-1204.190] started on the process from the link
[1204.200-1206.390] below. Then we have our raw, so I've got
[1206.400-1208.270] a a bunch of example raw entries.
[1208.280-1209.790] They're all things that have just gone
[1209.800-1212.270] in like this and then we have our wiki,
[1212.280-1214.110] which is all of the things it's created.
[1214.120-1216.550] So it created an index, which shows the
[1216.560-1220.230] key concepts within the system so far.
[1220.240-1222.070] And then within that, we then have all
[1222.080-1224.830] of the individual entries for like
[1224.840-1227.110] specific subjects. So
[1227.120-1229.950] effortless state, energy management,
[1229.960-1231.870] habit formation. So you you see these
[1231.880-1234.710] become themes, frameworks, templated
[1234.720-1240.830] ideas that are directed by the system.
[1242.790-1242.800] So now we need to ask it questions and
[1242.800-1245.070] get things out of it and it's this
[1245.080-1246.870] process that actually changes everything
[1246.880-1248.430] cuz every time you ask the agent a
[1248.440-1250.910] question you like the answer to, you can
[1250.920-1253.470] then save that back into raw or into the
[1253.480-1256.070] wiki and the system gets smarter the
[1256.080-1259.110] more you use it. So each question makes
[1259.120-1261.670] the next answer better. And that is
[1261.680-1264.150] because it's gone into outputs. So what
[1264.160-1265.430] we're going to do is just test this
[1265.440-1266.990] first of all. So I'm going to start a
[1267.000-1269.630] new window. I'd like to test out my new
[1269.640-1272.310] productivity knowledge base, and I have
[1272.320-1274.350] a question to ask you
[1274.360-1276.910] based on the knowledge base. What's the
[1276.920-1279.590] best way for me to balance achieving a
[1279.600-1281.950] huge amount in a short amount of time
[1281.960-1284.830] whilst managing my energy, happiness,
[1284.840-1286.270] and health? So, it's found the
[1286.280-1287.870] productivity knowledge base. It's
[1287.880-1289.830] reading the index. That's promising.
[1289.840-1292.110] Reading the most relevant wiki entries.
[1292.120-1294.230] This is a test. It should end up in
[1294.240-1297.790] here. It's comparing Newport, McEwen,
[1297.800-1299.550] and Burkhardt and Forte all covering
[1299.560-1301.470] this answer. You can't win both
[1301.480-1303.510] simultaneously. Trying to is what
[1303.520-1305.950] produces burnout. So, you can't do loads
[1305.960-1309.630] of work and rest. So, seven things the
[1309.640-1311.230] knowledge base says about that I can
[1311.240-1312.990] actually do. This is really cool. I
[1313.000-1314.350] really like this, and it's referencing
[1314.360-1315.910] where stuff is coming from. The test
[1315.920-1317.790] went well. The wiki had the article in
[1317.800-1319.190] every angle of your question. This is
[1319.200-1321.150] all great. Okay. So, we now need to
[1321.160-1322.710] check if it actually did an output.
[1322.720-1325.110] Let's have a look. Well, it didn't. So,
[1325.120-1327.070] okay, this is great, but we should have
[1327.080-1328.750] a rule within this system, which is when
[1328.760-1332.630] I ask question, the report is generated
[1332.640-1336.350] into outputs so that we are gaining
[1336.360-1340.510] deeper insights. So, please A, update
[1340.520-1343.030] the Claude MD to ensure that this is
[1343.040-1346.470] always the case. B, turn this into a
[1346.480-1349.470] report that goes into outputs. And C,
[1349.480-1352.190] then rerun the process with this query.
[1352.200-1354.190] Based on everything in the wiki, what
[1354.200-1355.870] are the three biggest gaps in my
[1355.880-1358.550] understanding of this topic? So, we go
[1358.560-1360.670] back in here. Please make sure you first
[1360.680-1362.590] reread the Claude MD for the knowledge
[1362.600-1364.710] base as I've now updated the topic
[1364.720-1366.310] focus. And I'm also going to add one
[1366.320-1368.630] more thing in here, which is write me a
[1368.640-1371.830] 500-word briefing on doing less but
[1371.840-1373.550] better using only what's in the
[1373.560-1375.230] knowledge base. Great. So, I'm going to
[1375.240-1376.710] ask that. So, we're doing a couple of
[1376.720-1377.790] things here. First of all, we're
[1377.800-1380.550] refining the system to make sure that it
[1380.560-1381.390] um
[1381.400-1384.550] always generates reports into outputs.
[1384.560-1386.990] Secondly, we want to turn the report
[1387.000-1389.310] it's just created into outputs. And
[1389.320-1390.270] thirdly, I'm going to give it two
[1390.280-1391.790] further tests,
[1391.800-1393.790] uh, answering these two questions. And
[1393.800-1395.150] I'm asking it to make sure it rereads
[1395.160-1397.310] the Claude MD for the knowledge base and
[1397.320-1399.230] now I've updated the topic focus. So, if
[1399.240-1401.510] we go and take a little look at the
[1401.520-1403.470] outputs and look at what it's written
[1403.480-1405.390] for us, we can see some great results
[1405.400-1407.110] here. It's saying it's looked at all the
[1407.120-1409.350] articles and it said it has almost
[1409.360-1411.070] nothing on the journey from where most
[1411.080-1413.310] people start, overcommitted, fragmented
[1413.320-1415.430] attention, default on connectivity.
[1415.440-1418.750] Cool. It's missing the mechanics of
[1418.760-1421.510] stopping and then it's got real decision
[1421.520-1423.630] method for what counts as essential.
[1423.640-1425.590] That's missing. It's missing working
[1425.600-1426.870] with other people, interestingly. It
[1426.880-1428.870] generally presumes that you're working
[1428.880-1430.670] on your own. This is really cool. So,
[1430.680-1433.870] what we could now do is go and use this
[1433.880-1436.830] to feed into the updates and
[1436.840-1438.150] improvements. And we can actually get
[1438.160-1441.270] the AI to build and improve on itself.
[1441.280-1442.950] Make sure that your instructions say
[1442.960-1445.190] read the outputs and work from there.
[1445.200-1447.470] So, now I'm going to show you step five,
[1447.480-1449.310] which is the health check. And this one
[1449.320-1451.710] really matters. The AI will sometimes
[1451.720-1453.590] write something slightly wrong, you'll
[1453.600-1455.550] save it back, and the next answer
[1455.560-1458.390] quietly builds on a mistake. So, once a
[1458.400-1460.470] month you want to audit this. And the
[1460.480-1462.390] prompt is going to be something like
[1462.400-1466.150] this.
[1468.030-1468.040] Now, I'm going to show you in a moment
[1468.040-1470.310] how to build a scheduled task and the
[1470.320-1471.950] skill to do that. But, first let's just
[1471.960-1473.790] do this really simply. And to do it, I'm
[1473.800-1475.910] actually just going to point this
[1475.920-1478.830] directly at the folder to demo this.
[1478.840-1481.430] We're going to co-work, we're going to
[1481.440-1483.550] knowledge base
[1483.560-1486.070] and this folder.
[1486.080-1487.630] So, if you just do this manually, you
[1487.640-1489.230] want to say something like this. Please
[1489.240-1491.710] review the entire productivity knowledge
[1491.720-1494.830] base wiki, flag contradictions and
[1494.840-1497.630] inconsistent data between articles, find
[1497.640-1499.910] missing data, and fill the gaps with web
[1499.920-1502.510] search. List claims not backed by a
[1502.520-1506.110] source in raw, and suggest connections
[1506.120-1508.230] between articles I haven't drawn yet,
[1508.240-1510.870] and three new article candidates. So,
[1510.880-1513.590] this is quality control. The one thing I
[1513.600-1515.270] am going to write here though is,
[1515.280-1518.230] "Please do not invoke my health check
[1518.240-1520.870] skill. This is a demo of just doing it
[1520.880-1522.790] clean with this instruction." Cuz I've
[1522.800-1524.390] created a health check skill. Let's try
[1524.400-1527.150] it. And now, as this is a demo, actually
[1527.160-1529.150] please just share your results and
[1529.160-1531.550] changes in the chat. Don't edit anything
[1531.560-1533.710] currently in the wikis. I'm just going
[1533.720-1535.110] to say that as well cuz I want to you
[1535.120-1536.390] just see the kind of thing it's going to
[1536.400-1538.150] do. So, what you can see it's now doing
[1538.160-1540.070] is reading through the wiki and the
[1540.080-1543.350] system and making a complete audit of
[1543.360-1544.710] the knowledge base. Now, you would just
[1544.720-1546.750] set this going, leave it, and come back.
[1546.760-1548.710] But even better, we can schedule it. And
[1548.720-1550.110] while it does that, I'll show you what
[1550.120-1552.270] that scheduled task looks like. If we go
[1552.280-1554.310] into scheduled,
[1554.320-1556.950] we now have this knowledge base monthly
[1556.960-1559.830] health check. All I did here was ask the
[1559.840-1561.870] system to create me
[1561.880-1565.830] a automated health check comprising of a
[1565.840-1568.550] knowledge base health check skill that
[1568.560-1571.190] it would create with its skill creator
[1571.200-1573.950] plugin. And it basically says, "Go
[1573.960-1575.710] through and do the things that we've
[1575.720-1577.630] just asked for based on the skill." You
[1577.640-1580.350] can set this up so that it runs on
[1580.360-1582.630] different times. But interestingly, you
[1582.640-1584.870] can have a custom schedule. So, if you
[1584.880-1586.910] ask it when you speak in the chat to
[1586.920-1589.710] build you a skill that is monthly, it
[1589.720-1592.070] can do that. Uh not just follow the
[1592.080-1593.750] options that are in the selectors. And
[1593.760-1595.630] that's it basically. It's ready to go.
[1595.640-1598.590] And you can get it to act without
[1598.600-1600.630] pausing for approval if you want. That's
[1600.640-1602.510] an option. So, I'm going to save that
[1602.520-1604.350] for now. And then if we go into
[1604.360-1606.910] customize, I've also created in skills
[1606.920-1609.910] this knowledge base health check skill.
[1609.920-1612.590] And this will work its way through the
[1612.600-1615.070] process. And it does it in two phases.
[1615.080-1617.550] It has a first order in file process
[1617.560-1619.590] where it reads my writing rules guide
[1619.600-1620.910] for anything that it's going to write.
[1620.920-1623.710] It reads the change log, the wiki, and
[1623.720-1626.270] what's been ingested, as well as the
[1626.280-1627.790] outputs that have been created since the
[1627.800-1630.910] last last health check. And then it runs
[1630.920-1632.750] a seven-stage audit. And the seven
[1632.760-1635.990] stages are these: contradictions, broken
[1636.000-1637.990] backlinks and orphaned references,
[1638.000-1639.790] source provenance,
[1639.800-1643.390] coverage that the raw files have, stale
[1643.400-1644.910] articles, anything that's out of date,
[1644.920-1646.710] older than 90 days and not relevant, and
[1646.720-1648.910] suggested new articles. And then this is
[1648.920-1650.550] a report template of how it gives a
[1650.560-1653.110] report. And then it has a second phase,
[1653.120-1654.310] which is if you're doing this
[1654.320-1655.510] interactively, if you're actually
[1655.520-1658.070] directly asking for it, it will also ask
[1658.080-1660.310] which findings to action and ask user
[1660.320-1661.710] question. So, it means you can kind of
[1661.720-1663.590] go through it fully and then fully uh
[1663.600-1665.150] commit it. In the phase one, it will
[1665.160-1666.870] just give us a report that we can then
[1666.880-1668.790] ask to be actioned later on. Now, I'm
[1668.800-1670.830] creating a templated version of this for
[1670.840-1672.670] you guys so you can just download it via
[1672.680-1674.510] the link in the description and use it.
[1674.520-1675.870] But for now, let's go and see what our
[1675.880-1679.390] example is up to. And here is our audit.
[1679.400-1681.750] Let's see what it says. Effort versus
[1681.760-1684.150] effortlessness, our contradictions,
[1684.160-1687.110] inconsistent numbers and framing, nice.
[1687.120-1689.550] It's cleaning up attribution drift,
[1689.560-1692.550] unsourced and under-sourced claims,
[1692.560-1694.590] building a second brain, mood first
[1694.600-1696.470] productivity, it's not captured the
[1696.480-1698.910] link, habit formation, so on and so
[1698.920-1701.390] forth, gaps the wiki has, there's no
[1701.400-1703.110] underlying research for the cathedral
[1703.120-1705.470] effect, we don't have the book, an
[1705.480-1707.070] unprocessed file that we haven't
[1707.080-1708.790] ingested, great. That's something I
[1708.800-1711.470] added recently, an unaccounted JPEG, and
[1711.480-1712.830] then it's found some really interesting
[1712.840-1716.190] connections that we might not have seen.
[1716.200-1718.990] So, quick verdicts. It's unusually clean
[1719.000-1720.950] for an early-stage knowledge base. All
[1720.960-1723.110] looks pretty solid. Main weaknesses:
[1723.120-1726.190] attribution, unprocessed raw files, not
[1726.200-1728.230] uh naming the underlying study,
[1728.240-1730.150] philosophical contradictions. Okay,
[1730.160-1731.710] great. We'll leave this here as I'm now
[1731.720-1733.550] going to start a new session and compare
[1733.560-1737.110] this with my skill and triggered
[1737.120-1738.910] scheduled task to see how the results
[1738.920-1740.350] compare. So, now we're going to start
[1740.360-1743.270] again and let's run my scheduled task.
[1743.280-1745.550] So, we can actually go to scheduled,
[1745.560-1747.310] click into the scheduled task and click
[1747.320-1748.470] run now.
[1748.480-1751.790] As simple as that. Now, if we go into
[1751.800-1753.470] the knowledge base, so you can see it's
[1753.480-1756.030] now um implement the the knowledge base
[1756.040-1757.790] health check skill.
[1757.800-1759.430] It's following that now and reading my
[1759.440-1761.990] writing rules. These are anti-AI writing
[1762.000-1763.910] rules. We can see that it's going to
[1763.920-1766.550] have checked the latest uh item in the
[1766.560-1768.350] change log.
[1768.360-1769.950] So, these are the
[1769.960-1771.790] latest updates. It's working
[1771.800-1773.990] chronologically. It's then going to read
[1774.000-1775.870] through all of the other files and we
[1775.880-1777.990] should see it now work. So, let's let
[1778.000-1780.030] that run and see what we get back. Oh,
[1780.040-1781.990] and if you're interested in this item
[1782.000-1784.270] here, push summary to BriefBuddy, I've
[1784.280-1785.790] actually created myself a little
[1785.800-1788.110] reporting app that is automatically
[1788.120-1790.910] updated and turns up on my phone. You
[1790.920-1792.670] don't need to do this. Uh the system
[1792.680-1795.310] will just essentially uh you'll see when
[1795.320-1797.830] the scheduled task has run, you'll see a
[1797.840-1800.470] little um blue dot for something and you
[1800.480-1801.750] can go and look at that and find the
[1801.760-1803.230] report and the brief. So, this for
[1803.240-1804.790] example is another scheduled task that
[1804.800-1806.590] I'm running and essentially draft stuff
[1806.600-1808.150] so I can go and look at them and work on
[1808.160-1810.030] it. So, when this goes blue, we'll be
[1810.040-1811.430] ready to see what's happened. Okay,
[1811.440-1813.190] great. So, that took it about 12
[1813.200-1815.230] minutes. Now, it is worth remembering
[1815.240-1816.990] that this probably is going to cost a
[1817.000-1818.710] few credits to do it. That's why I'm
[1818.720-1820.470] only scheduling this to be monthly and
[1820.480-1822.070] you might want to do it for each
[1822.080-1824.070] knowledge base you build on a different
[1824.080-1825.230] day so you don't just use all your
[1825.240-1827.230] credits up, but it's a really useful
[1827.240-1828.830] thing to be doing to make it powerful.
[1828.840-1830.750] So, we can see it turned up. You don't
[1830.760-1832.110] really need anything more than that. If
[1832.120-1833.230] you come into Claude, you'll see that
[1833.240-1835.070] this has happened and we can click on it
[1835.080-1836.990] in either position. We can go in and
[1837.000-1839.910] take a look and we can see it's
[1839.920-1841.910] completed it. It's run that. It's filed
[1841.920-1843.670] a report, the brief buddy thing I'll
[1843.680-1845.630] need to problem solve, but to be honest
[1845.640-1846.830] with you, I don't really need it to do
[1846.840-1848.550] that. And it will show them to us here,
[1848.560-1849.910] but we can just go over to our folders
[1849.920-1852.190] to see what's happened. The change log,
[1852.200-1853.870] first of all, will have been updated
[1853.880-1855.830] today. There you go, health check first
[1855.840-1857.710] run. And it's reported on what's
[1857.720-1860.230] happened. So, the system will know where
[1860.240-1862.150] it's at. That's great. And then in
[1862.160-1864.070] outputs, we can see here is our health
[1864.080-1865.910] check. There you go, we've got the wiki
[1865.920-1867.390] is unusually well aligned, it's done a
[1867.400-1868.710] similar thing.
[1868.720-1870.590] New candidates, so it's gone through and
[1870.600-1873.430] looked at the issues and discoveries, no
[1873.440-1875.310] stale articles.
[1875.320-1877.710] It's cleaned up some banned words,
[1877.720-1880.390] American spelling, and then we've got
[1880.400-1882.230] suggested new articles. This is probably
[1882.240-1884.190] where the real value is. So, it's
[1884.200-1885.790] suggesting we look at collaborative
[1885.800-1889.310] productivity, good habit rest recipes,
[1889.320-1892.430] looking at B BJ Fogg, interesting. And
[1892.440-1894.910] we've got effort versus effortlessness,
[1894.920-1896.950] making the frame easy accepting strain
[1896.960-1899.150] inside, interesting. And then it's got
[1899.160-1901.790] an action menu. So, for phase two,
[1901.800-1903.830] things that it could run. And we could
[1903.840-1905.950] now ask it to run those things, and we
[1905.960-1908.230] will get that automatic update. So, this
[1908.240-1910.950] is a reasonably like in-depth process.
[1910.960-1912.750] You could always simplify it. It really
[1912.760-1914.310] comes down to what you want to do. But,
[1914.320-1916.270] check out the templated options in the
[1916.280-1917.750] description, and you can take it from
[1917.760-1919.430] there. Or, if you're downloading my
[1919.440-1921.750] Co-worker OS, it will be baked in. So,
[1921.760-1923.350] as a final example here, I'm going to
[1923.360-1925.630] get it to actually update.
[1925.640-1927.670] Please see the latest health check in
[1927.680-1929.590] your productivity knowledge base, and
[1929.600-1931.910] run the action list from it on that
[1931.920-1933.550] knowledge base. Now, what you can see is
[1933.560-1935.150] it's it's written itself a great list,
[1935.160-1937.510] it's applying the writing rule fixes,
[1937.520-1940.030] it's adding the new stuff to ingest,
[1940.040-1942.350] drafting the new articles, and then it's
[1942.360-1943.750] going to update everything, which is
[1943.760-1945.790] great. It's worth saying, I think for
[1945.800-1947.710] most people, once you've tested it in
[1947.720-1949.310] these two stages,
[1949.320-1951.190] it's quite easy for you just to have it
[1951.200-1952.710] automatically do it. So, you could just
[1952.720-1955.270] say, just do the work. Report and
[1955.280-1957.070] action. I think that's better. And
[1957.080-1959.550] potentially, you kind of refine your
[1959.560-1961.750] instructions to make it rigorous but not
[1961.760-1964.390] cost you loads and loads of credits. As
[1964.400-1966.790] an example, for the example that we've
[1966.800-1968.630] run, so the first one I did without the
[1968.640-1970.830] skills, then the one with the skill, and
[1970.840-1973.830] this, the usage of my Max plan for this
[1973.840-1976.590] current session is at 45%. That's on a
[1976.600-1978.830] 5x Max plan, so that's a significant use
[1978.840-1981.030] of credits. But once a month, for a
[1981.040-1983.510] really powerful knowledge base, not too
[1983.520-1985.390] bad. Let me know in the comments how you
[1985.400-1987.110] feel about that. And here we go, we've
[1987.120-1989.950] got the results. It's created new
[1989.960-1992.590] articles on habit receipts, working with
[1992.600-1995.230] others, and effort versus effortlessness
[1995.240-1997.190] into the gaps that were missing. It's
[1997.200-2000.230] updated the index questions and change
[2000.240-2002.750] logs, and they're all ingested, which is
[2002.760-2005.150] really cool. It's given me a bit of
[2005.160-2007.670] feedback about some web search stuff,
[2007.680-2009.270] and then it's created the documents. And
[2009.280-2011.190] if we go and check out the files, we'll
[2011.200-2014.390] see the new items have been ingested.
[2014.400-2017.270] And the new entries in the wiki have
[2017.280-2022.710] been added, which is great.
[2024.710-2024.720] So it should be that we now get a very
[2024.720-2027.510] different result. So if we ask, in a new
[2027.520-2029.510] task, "Take a look at the productivity
[2029.520-2032.070] knowledge base and give me a report on
[2032.080-2036.030] how I can balance making serious and
[2036.040-2039.230] useful effort versus making my week and
[2039.240-2041.910] days feel effortless in how I contribute
[2041.920-2043.590] to my life." These are just examples,
[2043.600-2044.990] right? But let's just drop it in and see
[2045.000-2046.510] what it gives us. And it's created it.
[2046.520-2048.030] Now annoyingly, it's not presented it to
[2048.040-2050.550] me. "Please can you update your Claude
[2050.560-2053.909] MD files and the templated one for
[2053.919-2055.669] knowledge bases
[2055.679-2058.389] so that any report that's created in
[2058.399-2060.510] response to a question is presented as a
[2060.520-2063.110] clickable page to open in the chat."
[2063.120-2065.030] Great, there we go. And it's now shown
[2065.040-2067.230] it to me, so I can actually click on it
[2067.240-2068.710] and read it. And this is what it's given
[2068.720-2070.669] us, a little report. Now here's a nice
[2070.679-2072.710] little tip, if you ever want to make
[2072.720-2074.669] your learning easier when you're doing
[2074.679-2077.030] this, I use Speechify to read things
[2077.040-2078.990] back to me so I can just do control
[2079.000-2080.869] option A and it reads it.
[2080.879-2082.669] &gt;&gt; The question: How can I balance making
[2082.679-2084.590] serious and useful effort versus making
[2084.600-2086.550] my week and days feel effortless and how
[2086.560-2087.710] I contribute to my life?
[2087.720-2089.430] &gt;&gt; Those are the five steps to building,
[2089.440-2091.750] refining, and using a knowledge base
[2091.760-2096.430] that learns as it goes.
[2097.910-2097.920] So, here's the bit you need to remember
[2097.920-2099.590] to take away with you. Day one of
[2099.600-2101.470] running this, your knowledge base isn't
[2101.480-2103.590] going to do loads. It's got whatever you
[2103.600-2105.870] dumped in over the weekend, useful but
[2105.880-2108.750] not revolutionary. But day 100, then
[2108.760-2109.870] you've actually built something
[2109.880-2111.790] valuable. Every meeting transcript that
[2111.800-2114.510] mattered, every answer you've saved back
[2114.520-2116.630] into the system becomes a carefully
[2116.640-2118.750] curated, cross-referenced, linked, and
[2118.760-2120.950] summarized set of information that you
[2120.960-2124.390] can query with the librarian themselves.
[2124.400-2125.790] And it's that kind of asset that's
[2125.800-2127.790] nearly impossible to replicate because
[2127.800-2129.910] nobody else has read what you've read or
[2129.920-2132.190] saved what you've saved. So, if you only
[2132.200-2134.430] do one thing from any video I make this
[2134.440-2137.430] year, do this. It's 45 minutes on a
[2137.440-2138.990] Saturday morning and you'll thank
[2139.000-2141.550] yourself in 3 months. One last thing,
[2141.560-2143.710] everything we built today, the folders,
[2143.720-2145.510] the Claude MD, the prompt, the health
[2145.520-2147.790] check, they all ship inside the final
[2147.800-2150.590] version of my Claude Co-worker OS when
[2150.600-2152.590] it comes out. It's in beta as I film
[2152.600-2154.470] this and you can download it right now.
[2154.480-2155.990] It's been brilliantly received so far.
[2156.000-2157.710] The whole point of it is to help you
[2157.720-2160.150] skip past the fiddly setup bits and land
[2160.160-2161.990] on a working Claude environment faster
[2162.000-2164.030] than most people manage on their own.
[2164.040-2166.350] It's been a game-changer for me and a
[2166.360-2168.470] lot of others using it. And of course,
[2168.480-2170.430] you can watch the video that shows you
[2170.440-2172.230] exactly how to do all of that right
[2172.240-2176.800] here. I'll see you on the next one. Bye.
