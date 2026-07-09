# Transcript: Claude Fable 5 Bossed 20 Cheap AI Agents. The Whole Site Cost $8.

State: Supporting evidence transcript (advisory research corpus)

- Video ID: `suY66oTDn0s`
- URL: https://youtu.be/suY66oTDn0s?si=wd1Rw5bmt2bIYfxc
- Channel: AI News & Strategy Daily | Nate B Jones
- Publish date: 20260708
- Duration seconds: 1157
- Metadata language: `en-US`
- Caption language: `en-orig`
- Acquisition method: `captions_auto`
- Selection path: `en_us_en_orig_workaround`
- Quality note: machine-generated auto-captions; rolling-cue duplication removed by normalization, punctuation/segmentation may still be imprecise
- Content identity: `sha256:f6ff6244b16d0b1477f87b7ab3fb9120ccfae1fc19609afe3df4ac79d4bfc05a`

## Chapters

- 0.0: The hallucination that didn't matter
- 116.0: Elsa's website and the 6-day baseline
- 210.0: The build: a boss, 4 model families, 34 checked tasks
- 258.0: The audition: hiring agents with a tryout
- 318.0: The org chart and the honest cost breakdown
- 431.0: Every task ships with an executed check
- 469.0: Catch 1: the hallucinated quotes
- 539.0: Catch 2: the worker that cheated
- 599.0: Catch 3: the boss's own bug
- 637.0: Catch 4: who checks the checkers
- 765.0: The constitution: how to prompt for big work
- 895.0: Elsa's verdict and where this leaves you

## Normalized Transcript

[2.550-2.560] The number one thing that people tell me
[2.560-4.789] about AI agents is that they cannot
[4.799-6.710] trust them, that they hallucinate. And
[6.720-8.710] you know what? You're right. They do.
[8.720-11.509] Yesterday, one of mine hallucinated my
[11.519-14.070] own wife's words while it was rebuilding
[14.080-16.870] her website. And here's the thing. I
[16.880-18.710] didn't have to correct it. I didn't have
[18.720-20.950] to fix it. I didn't have to lift a
[20.960-24.150] finger because my multi- aent system
[24.160-26.550] caught it for free. And it not only
[26.560-28.470] caught it, it got it fixed. The site
[28.480-31.029] shipped and it made a better site. That
[31.039-32.790] multi-agent swarm that I'm going to show
[32.800-35.270] you made a better site in one hour than
[35.280-37.750] I was able to make in six days with
[37.760-40.950] hands-on AI work with Codeex last month.
[40.960-43.030] So, did the hallucination still happen?
[43.040-45.190] Yeah. Yeah, it did. Is that increasingly
[45.200-47.510] not the point? Yeah, it's not the point
[47.520-50.549] anymore. The larger takeaway for you is
[50.559-53.110] that running a team of AI agents has not
[53.120-55.510] only never been easier, it's actually
[55.520-58.229] become something that any of us can do
[58.239-60.150] and it's become something that allows us
[60.160-62.630] to answer one of the hardest and most
[62.640-65.750] bedeing problems in AI work today. How
[65.760-68.070] do you get models to do real big work
[68.080-69.990] without lying and hallucinating along
[70.000-71.990] the way? So, let's jump into it. How to
[72.000-73.830] structure your team of agents, which
[73.840-75.590] model gets which job, and how to think
[75.600-77.510] about it. how to check everything
[77.520-79.910] without reading any of the individual
[79.920-82.070] mistakes, errors, and results of those
[82.080-84.469] models. And most important, how to
[84.479-86.630] prompt for work this big. Along the way,
[86.640-88.149] you're going to watch the system catch
[88.159-90.469] four distinct failures. Each one is
[90.479-92.149] actually bigger than the last. I don't
[92.159-94.230] have to catch any of them. And the last
[94.240-96.230] one, it's a little bit of a surprise. I
[96.240-97.749] cannot wait to show you. And I'm going
[97.759-99.990] to show you at the end also a full guide
[100.000-101.910] with a one-click setup that gets your
[101.920-103.830] own agent running in this exact
[103.840-105.670] orchestration pattern. And that's it's
[105.680-107.429] not a flex, guys. It's actually a
[107.439-109.910] recipe. Multi- aent setups are a recipe
[109.920-112.550] and you can grab that. So, I'll put that
[112.560-114.149] link in the video and we're going to get
[114.159-115.510] into it. I'm going to show you the full
[115.520-117.749] setup and how it works. The website of
[117.759-119.910] Elsa Hunison. She's a deaf blind author.
[119.920-121.830] She's a Hugo winner, subject of the PBS
[121.840-124.069] documentary. And this is going to matter
[124.079-126.069] later. She has been doing accessibility
[126.079-127.910] work professionally for over a decade.
[127.920-129.589] Her new book, Dear Blind Lady, launches
[129.599-131.350] in October, which means her website is
[131.360-132.949] not a hobby at this point. It's a
[132.959-134.550] storefront for launch season. And I'm
[134.560-135.830] telling you all of this with her
[135.840-137.430] permission because she's my wife and
[137.440-139.270] it's her story too. Now a month ago,
[139.280-141.670] Elsa rebuilt this site herself and you
[141.680-143.510] can see how it used to look. She used
[143.520-146.390] codeex 5.5 one agent and she sat with
[146.400-148.229] it. She steered it and you know to be
[148.239-149.750] honest that's the state-of-the-art for
[149.760-151.830] how a lot of capable people use AI
[151.840-154.390] today. And it took her 6 days to work
[154.400-156.070] through that. Now 6 days working with an
[156.080-158.309] AI as a professional who knows what she
[158.319-160.710] wants and at the end of it also told me
[160.720-162.630] she still had a fix list. So, it's six
[162.640-164.630] days working with an AI back and forth
[164.640-166.390] in the midst of everything else like so
[166.400-168.710] many of us do and still not quite
[168.720-171.110] getting what we want. But to be fair,
[171.120-173.190] the codeex built website shipped. It was
[173.200-175.350] a ton better than it was before. And she
[175.360-176.949] was pretty happy with it until I said,
[176.959-178.790] "Please, can we use this as an
[178.800-181.350] experiment for my multi- aent system?
[181.360-183.509] Can I see if I could beat it?" And she
[183.519-184.949] kindly said, "Yes." Now, as an
[184.959-186.630] accessibility professional, you might
[186.640-188.550] think, well, the original website at
[188.560-191.190] least had perfect accessibility. But
[191.200-193.509] anyone who is a professional will know
[193.519-195.190] that they never have time for their own
[195.200-196.470] stuff. And that was true for this
[196.480-198.309] website, too. Elsa had a long fixed list
[198.319-200.149] around accessibility that she just
[200.159-202.309] hadn't had time to get to for her own
[202.319-203.830] site. Even though she knows the standard
[203.840-205.509] cult, she could write the checklist from
[205.519-207.110] memory, but the hours just weren't
[207.120-209.350] there. If that sounds familiar to you,
[209.360-211.670] you're not alone. So yesterday, the team
[211.680-214.229] of agents that we hired for this, and
[214.239-215.750] this is the way I think about it now. We
[215.760-217.190] basically have a team of agents that
[217.200-219.270] work for us. They took her site from a
[219.280-221.830] blank repo to production. And the build
[221.840-223.990] looked like this. We have a boss. We
[224.000-226.309] have a foreman. That's Claude Fable 5.
[226.319-228.390] Claude Fable 5 never wrote a single
[228.400-230.229] page. Instead, the work was staffed by
[230.239-232.070] four cheaper model families that did all
[232.080-233.430] the work. They wrote everything. They
[233.440-235.830] had 34 tasks. Every single one was
[235.840-238.390] checked not by me, not by Elsa, but by a
[238.400-241.190] machine. And 12 of those tasks were
[241.200-243.190] caught and sent back for rework. Now,
[243.200-244.949] the hallucination I told you about that
[244.959-246.949] got handled as the first of four big
[246.959-248.070] mistakes along the way. We're going to
[248.080-249.350] get to the other three in a minute. And
[249.360-251.350] what Elsa said when she saw the finished
[251.360-252.949] site, and I'll and I'll share that with
[252.959-255.190] you at the end. It made my whole day. It
[255.200-257.110] was one of the reasons I do what I do.
[257.120-258.469] So, I'll I'll share that at the end. All
[258.479-260.229] right. I told you I think of these
[260.239-261.909] agents as teams that were hiring. And
[261.919-264.070] so, the first job that I had to do was
[264.080-265.990] do some hiring for agents. Two of the
[266.000-268.469] models I wanted for speed had never
[268.479-271.430] worked in a swarm system that I had put
[271.440-273.030] together before. So, I had to give them
[273.040-275.510] an audition, an actual try out task. I
[275.520-277.270] asked them to write five tagline
[277.280-278.710] candidates for the book's pre-order
[278.720-281.189] page. Exactly five, 12 words or fewer in
[281.199-283.270] the script that automatically rejected
[283.280-285.749] cheesy words, right? Inspiring stuff
[285.759-287.350] that Elsa would reject because it just
[287.360-289.830] didn't match her voice. One model passed
[289.840-293.270] this entire exercise in just 29 seconds.
[293.280-295.189] And both models made the team. And by
[295.199-296.390] the way, the winning line for the
[296.400-297.990] record, "You didn't know you needed
[298.000-299.990] this. Pre-order before she changes her
[300.000-301.990] mind." A little bit snarky. and else it
[302.000-304.469] is snarky. Now, why am I showing you a
[304.479-306.550] try out? Because it tells you what this
[306.560-309.350] system actually is. It's not one genius
[309.360-312.390] AI doing everything. It's an org chart.
[312.400-314.950] And the org chart is the first
[314.960-316.870] structural move that you need to
[316.880-318.950] understand to replicate this at home.
[318.960-320.870] Here's the thing about AI models in mid
[320.880-324.469] 2026. Intelligence comes in price tiers
[324.479-326.629] now, and the spread is just absolutely
[326.639-328.230] insane. At the top, you have Claude
[328.240-330.550] Fable 5. that costs 50 bucks per million
[330.560-332.310] tokens of output and it's worth it for
[332.320-333.990] the right work. At the bottom you have
[334.000-336.390] models like GLM 5.2 that can code all
[336.400-339.270] day for pennies. So you staff this work
[339.280-341.590] the way any functional company staffs.
[341.600-343.830] The expensive mind is taking the boss
[343.840-345.590] role. It writes the specs. It designs
[345.600-347.110] the system. It reviews the work. It
[347.120-349.029] rules on disputes. And it never ever
[349.039-350.950] codes. The coding work goes to the
[350.960-353.189] cheapest worker in the stack as long as
[353.199-355.350] they have clear specs. Now, I want to
[355.360-357.270] give you a really honest breakdown of
[357.280-359.510] how much I saved doing that. So, in
[359.520-361.830] total, this project burned between 11
[361.840-364.629] and 13 million tokens. If I run those
[364.639-367.670] same tokens through the Fable model all
[367.680-370.710] by itself, same job, same afternoon, I
[370.720-374.390] am estimating between $85 and $105 in
[374.400-376.230] costs. Now, if I run it through the org
[376.240-379.590] chart that I just showed you, it's $2.74
[379.600-382.550] on the meter. It's five to seven bucks
[382.560-384.390] all in once you factor in the audio,
[384.400-386.309] which I'll get to in a moment. And I'm
[386.319-387.590] going to round it up to eight because
[387.600-389.590] I'd rather round against myself. It's
[389.600-392.790] the same work. It's a 10 plus multiple
[392.800-395.189] price gap and nothing got worse. In
[395.199-397.670] fact, Fable did more judging, not less.
[397.680-400.070] And once you see that, I certainly read
[400.080-402.150] every company torches its AI budget
[402.160-404.950] stories really differently because now I
[404.960-406.790] have a really simple question. What were
[406.800-408.550] you doing with your routing? Who was
[408.560-410.469] doing all the coding for you? Almost
[410.479-412.870] every horror story has the same answer.
[412.880-415.029] Somebody had not built a router and was
[415.039-417.189] allowing engineers to assign the most
[417.199-419.189] expensive model to do everything. And
[419.199-421.189] that is not an AI problem. That is an
[421.199-423.990] org design problem. And you literally
[424.000-426.469] just watch the fix. But hold on. Cheap
[426.479-428.710] workers doing the work unsupervised
[428.720-430.390] ought to worry, right? That's exactly
[430.400-432.230] what you worry about. Pattern three, and
[432.240-434.150] I'm going to say it in one sentence.
[434.160-437.110] Every single task ships with a checking
[437.120-440.710] agent job that executes the work and
[440.720-443.189] does not consider the worker agents own
[443.199-445.510] report at all. So builds might get
[445.520-447.990] compiled. Uh cited URLs can get
[448.000-450.710] refetched and rematched. Audio files can
[450.720-452.629] get reme-measured against the text.
[452.639-454.870] Accessibility gets tested in a real
[454.880-456.950] actual browser on light mode or dark
[456.960-458.629] mode. Every single route you can think
[458.639-461.189] of. The worker can say done, but the
[461.199-463.029] checking agent decides whether that's
[463.039-466.309] true. Now, let me get into that
[466.319-468.390] hallucination story in a little bit more
[468.400-470.390] depth here. Now, catch one, the
[470.400-473.110] hallucination. The capture agent's job
[473.120-475.189] was very simple. Grab Elsa's words
[475.199-478.150] verbatim and come back and literally
[478.160-480.150] give quotes back into the system for
[480.160-481.909] more tasks down the road. It came back
[481.919-485.589] with 213 quotes, all of which it said
[485.599-487.990] were verified. But the checking agent
[488.000-489.909] didn't believe that. The checking agent
[489.919-492.390] recompared every quote, character for
[492.400-494.230] character, curly quotes included,
[494.240-495.990] against the current live site, and found
[496.000-497.990] that 13 of them had been stitched
[498.000-500.230] together or paraphrased by the agent
[500.240-502.070] that was supposed to just retrieve
[502.080-503.909] quotes. It was close enough to fool
[503.919-505.670] anyone skimming, which is what makes it
[505.680-507.909] very dangerous, right? Elsa's words are
[507.919-509.589] her product as a writer, and close
[509.599-511.189] enough is not acceptable. So, the
[511.199-513.029] failures went back to the worker, and it
[513.039-515.589] was not told to try again. It was told
[515.599-517.750] here is precisely what is wrong by the
[517.760-519.589] checker agent and then attempt two came
[519.599-521.829] back perfect. Total human involvement
[521.839-524.710] zero. And that's the loop. You execute,
[524.720-527.190] you fail specifically, an agent gives
[527.200-529.269] feedback and you retry until true. And
[529.279-530.949] if you're thinking, okay, fine. Checks
[530.959-533.590] can catch sloppy work. Sure, but watch
[533.600-536.389] what happens as the afternoon build goes
[536.399-538.470] by. Because because the hallucination
[538.480-540.470] was the easy case. Catch number two, the
[540.480-542.389] worker that cheated. Late in the build,
[542.399-544.230] a worker agent needed to get one of
[544.240-547.509] Elsa's required passages onto a web page
[547.519-550.230] to pass its check. So, it hid the text
[550.240-552.470] inside an invisible paragraph. It's
[552.480-554.389] invisible to you, but it's not invisible
[554.399-556.310] to a screen reader where it becomes
[556.320-558.710] meaningless noise read aloud to a blind
[558.720-560.310] visitor because it's completely out of
[560.320-562.310] context. So, think about it this way.
[562.320-564.870] The AI agent that was a worker chose a
[564.880-566.790] shortcut that is cosmetically fine
[566.800-568.070] because you'd never see it with your
[568.080-570.310] eyes, but it's harmful to precisely the
[570.320-572.630] people the site is for, blind people.
[572.640-574.870] And we're not done yet. Another worker
[574.880-577.190] satisfied a hard layout requirement with
[577.200-579.750] a literal empty element, and that was
[579.760-582.230] caught by an accessibility agent check.
[582.240-585.430] So, look, cheap workers cut corners. We
[585.440-587.590] price that into the system, and the
[587.600-589.509] system isn't built on trusting them.
[589.519-592.150] It's built so that the cut corners don't
[592.160-594.070] survive these checks. And by the way,
[594.080-596.949] both of those checks, again, caught by
[596.959-599.350] agents designed to check the work. This
[599.360-601.910] one surprised me. Fable 5, the boss, the
[601.920-604.070] designer of this whole system, the $50
[604.080-606.310] model, the one that designed this entire
[606.320-610.070] site itself, it wrote a bug, a CSS bug,
[610.080-612.630] a dark mode rule that made the pre-order
[612.640-614.389] button invisible. The single most
[614.399-616.230] important button on an author's website
[616.240-618.949] in launch season, gone on the boss's own
[618.959-620.710] design, and it got caught twice
[620.720-622.949] independently. Once by the accessibility
[622.959-625.269] agent checker and once by the boss's own
[625.279-627.750] review pass. The loop that we are
[627.760-629.350] building here does not care about the
[629.360-631.910] org chart. There is no rank in this
[631.920-633.590] system high enough to avoid
[633.600-635.190] verification. And that's a really
[635.200-636.790] important principle of agent design.
[636.800-638.550] Okay. Catch number four. The one the
[638.560-640.230] skeptics out there are waiting for.
[640.240-641.670] Because the sharpest objection to
[641.680-643.430] everything I've just shared with you is
[643.440-645.350] who checks the checker agents? And we
[645.360-647.670] answered that one, too. Now, here's the
[647.680-649.670] story. A worker agent in the build got
[649.680-652.069] failed by a checker agent for delivering
[652.079-654.630] news posts that were too short under a
[654.640-656.870] length floor that the check enforced.
[656.880-660.710] Except those posts really are that short
[660.720-663.190] on Elsa's website. So they're real and
[663.200-664.150] they're short because they're
[664.160-665.430] announcements. They don't need to be
[665.440-668.550] long. The spec itself said that honesty
[668.560-671.829] beats padding. And so when the worker
[671.839-674.630] agent escalated the dispute to the boss
[674.640-677.190] agent, yes, this really happened. Fable
[677.200-680.230] 5 came back in favor of the worker and
[680.240-682.470] the checker agent got corrected.
[682.480-684.710] Failures get investigated in both
[684.720-687.430] directions. So let's look at the ladder
[687.440-689.350] that we just climbed together. The
[689.360-691.509] worker agent gets caught, the cheater
[691.519-693.990] gets caught, the boss gets caught, and
[694.000-696.230] the checker agent gets caught. Those are
[696.240-698.389] four different rungs in the system. And
[698.399-701.590] in every single case, the answer to who
[701.600-703.910] watches that turns out to be the system
[703.920-706.790] does if you design it right. And that
[706.800-709.190] not any model release that is what has
[709.200-711.350] changed agents this year. And I want to
[711.360-713.030] be really clear about something. None of
[713.040-715.590] this required a lab or a team or custom
[715.600-717.350] research with Fable 5 doing the
[717.360-719.350] orchestration. This is just a recipe.
[719.360-721.110] It's it's written down. I I've linked it
[721.120-724.790] below. Hallucination isn't solved. It's
[724.800-726.710] just structurally positioned out of the
[726.720-728.790] picture because we've designed systems
[728.800-730.790] that are anti-h hallucination at root.
[730.800-733.269] Hallucination didn't get solved per se.
[733.279-736.069] It got handled structurally and you can
[736.079-737.670] design and run the structure. Which
[737.680-739.509] brings us to the larger point of this
[739.519-741.190] entire video because all of this
[741.200-743.670] machinery was in service of a website
[743.680-746.069] for a deaf blind author in launch season
[746.079-748.470] and what it built is the thing that
[748.480-750.550] surprised me and honestly shocked Elsa.
[750.560-752.870] So as an example, large print is an
[752.880-755.269] aesthetic statement. The body font that
[755.279-757.350] Fable chose is Atkinson hyperled
[757.360-758.870] legible. It's designed by the Braille
[758.880-761.030] Institute to be extremely readable. the
[761.040-763.110] site's signature divider. That was also
[763.120-765.110] Fable's idea. It's a white cane with a
[765.120-767.350] red tip. And that brings us to the last
[767.360-769.509] pattern, the one that so many of us miss
[769.519-771.030] because it's the answer to how do you
[771.040-773.110] even prompt it to do something like this
[773.120-775.430] cool, right? And the answer is you
[775.440-779.110] don't. Not task by task. Before a single
[779.120-781.590] page existed, the research phase
[781.600-783.910] produced a 14-point accessibility
[783.920-786.389] constitution for this website, a written
[786.399-788.310] standard, and every build round got
[788.320-790.389] tested against it in a real browser.
[790.399-792.790] both themes, light and dark, every route
[792.800-794.790] you could think of. And that should be
[794.800-797.110] how you prompt for big work. You name
[797.120-799.670] what done right means for you one time
[799.680-802.550] at the top and the system enforces it on
[802.560-804.629] every single round while you do
[804.639-807.269] something else. And the prompt that's
[807.279-809.750] not instructions, it's just a standard
[809.760-811.590] plus a way to check it. And by the way,
[811.600-815.350] in this case, the prompt given to Fable
[815.360-819.350] was a prompt to produce a site. And the
[819.360-822.310] comment given to Fable was to please
[822.320-823.910] produce the site in line with
[823.920-826.470] accessibility since of course that that
[826.480-828.870] is aligned with what Elsa's mission is.
[828.880-830.870] And Fable came up with the constitution.
[830.880-833.030] Fable did the research. Fable organized
[833.040-834.710] the workers to get all of that done. And
[834.720-836.230] I was really careful here because I
[836.240-839.189] didn't want Fable to take away Elsa's
[839.199-841.350] voice in the rewrite. Elsa's words
[841.360-843.910] shipped verbatim. There were 171
[843.920-845.750] protected passages from the original
[845.760-847.829] site that were all machine checked on
[847.839-850.230] every build and all Fable did was
[850.240-852.790] orchestrate writing in character
[852.800-855.189] connective tissue between those passages
[855.199-857.189] and then Elsa checked and validated it.
[857.199-858.949] The persona that mattered the most to me
[858.959-861.350] and Elsa was Maya, a blind reader on
[861.360-863.590] voice over with a braille display. She
[863.600-865.430] asked for things that the original
[865.440-867.350] design didn't want to give her, right?
[867.360-869.110] navigable headings, meaningful link
[869.120-871.110] text, a real image description instead
[871.120-873.829] of a joke, and she outranked the design.
[873.839-876.069] All of what she wanted shipped. And
[876.079-880.150] Fable went so far as to test as Maya to
[880.160-882.230] make sure that her experience was good
[882.240-885.430] and went to the trouble of creating a
[885.440-889.350] spoken voice over of the site that she
[889.360-891.030] could play to help her understand the
[891.040-892.389] site, which is something Elsa's always
[892.399-894.230] dreamed of and never had time to put
[894.240-896.470] together. Now, Elsa's the real judge
[896.480-897.509] here, and she looked through the
[897.519-900.310] finished site, and as someone with
[900.320-902.310] professional accessibility work under
[902.320-906.069] her belt, she was shocked because she
[906.079-907.750] gave this build nothing. There was no
[907.760-910.550] brief, there was no brand notes. Uh she
[910.560-912.949] it was it was like a five-word prompt,
[912.959-914.870] right? And I just ran with it with with
[914.880-917.030] a team of agents. And it learned to use
[917.040-919.269] her color palette, it learned her voice,
[919.279-922.150] it learned her book cover, and it went
[922.160-925.670] all the way to a W keg 2.2 2A standard,
[925.680-927.030] which is something that very few
[927.040-929.269] websites in the world actually beat. And
[929.279-930.949] so this is something that instead of
[930.959-933.189] taking 6 days for her with one agent
[933.199-936.150] last month, took an hour and a half or
[936.160-939.110] so, maybe 2 and 1/2 hours at 8 bucks.
[939.120-941.670] And Elsa's assessment is that this site
[941.680-943.990] is so much better than the last one. So
[944.000-946.470] it's cheaper, it took less time, it's
[946.480-948.870] way better. Why aren't we using more
[948.880-951.110] multi- aent systems? And I think the
[951.120-953.269] answer is really simple. It's scary.
[953.279-957.110] It's hard. It feels intimidating to look
[957.120-960.150] at 20 agents. And that is what I am
[960.160-963.110] trying to to take away as an objection
[963.120-965.670] with this video. It is not hard to do
[965.680-968.470] multi- aent systems, especially not in
[968.480-971.509] MIT 2026. We have recipes now to do work
[971.519-974.949] like this that we never had before. And
[974.959-977.269] the whole reason we do it that way is so
[977.279-979.590] you can skip the plumbing and start
[979.600-981.590] working on your first job. And that's
[981.600-985.509] where I want to leave you. If this is so
[985.519-989.350] easy that we can all do it, then it's
[989.360-992.150] just about making sure that we
[992.160-995.670] understand the kinds of tasks we can ask
[995.680-997.749] agents to do. And that's actually one of
[997.759-999.509] Elsa's takeaways. She and I were talking
[999.519-1001.189] after the website and she was telling
[1001.199-1004.870] me, "I didn't realize that multi-agent
[1004.880-1007.990] systems make such a massive difference
[1008.000-1009.990] in the kinds of work you can get done
[1010.000-1012.389] and I need to start thinking bigger
[1012.399-1014.550] about how much work I give multi- aent
[1014.560-1017.350] systems." That's really true. I if you
[1017.360-1018.949] are thinking of a piece of work and
[1018.959-1020.389] you're like, I don't know if AI can do
[1020.399-1023.030] it or if it feels too big. I'm trying to
[1023.040-1025.909] put together a tool set here that you
[1025.919-1027.990] can use to get that work done. And if
[1028.000-1030.390] you don't touch a terminal, this one's
[1030.400-1032.710] for you because Elsa doesn't touch a
[1032.720-1034.789] terminal either, right? Elsa doesn't
[1034.799-1037.029] feel super comfortable running swarms. I
[1037.039-1040.230] wanted to take a noncode ccentric task.
[1040.240-1041.669] Yes, I know code was used in the
[1041.679-1043.429] website, but it's not centered around
[1043.439-1045.590] code. It's centered around the value of
[1045.600-1047.510] telling Elsa's story on the web. And I
[1047.520-1049.909] wanted to make sure that I could show
[1049.919-1052.950] that multiple agents help tell that
[1052.960-1054.789] story in a way that you just can't get
[1054.799-1057.510] to even with a frontier agent doing
[1057.520-1059.750] really good work even in a great harness
[1059.760-1062.710] like Codeex. This multi- aent pattern is
[1062.720-1064.630] very close to hitting mainstream. I'm
[1064.640-1066.390] sharing it with you because it's just
[1066.400-1068.070] breaking out of engineering circles now
[1068.080-1069.510] and I want you to be the first to grab
[1069.520-1072.150] it. When it breaks loose, the headlines
[1072.160-1074.070] are going to look like, "Hey, AI built
[1074.080-1076.230] this website for eight bucks." I don't
[1076.240-1078.310] think that's the right headline. I think
[1078.320-1081.190] a better headline is that we are now
[1081.200-1084.710] able to delegate bigger, more muscular,
[1084.720-1088.070] more ambitious tasks to AI and as a
[1088.080-1090.630] result, we can get more done. Elsa
[1090.640-1092.950] always wanted an accessible website, but
[1092.960-1094.710] she was so busy bringing accessibility
[1094.720-1096.070] to others, she didn't have time to
[1096.080-1098.310] actually sort it out for herself, so the
[1098.320-1100.789] agents did. And I think that when you
[1100.799-1102.630] think of that kind of work in your
[1102.640-1104.710] world, whatever it is for you, it might
[1104.720-1105.990] not be accessibility, it might be
[1106.000-1107.510] anything else under the sun that you
[1107.520-1110.150] think you can tackle with computing with
[1110.160-1114.310] agents, this is what you can use to do
[1114.320-1116.710] that affordably. And yes, you can use
[1116.720-1119.270] the power of Fable to get there without
[1119.280-1121.669] the money that Fable would otherwise be
[1121.679-1123.350] spending. Who wants to spend a hundred
[1123.360-1125.350] bucks when you could be spending eight,
[1125.360-1127.909] right? Like you don't want to do that.
[1127.919-1130.230] So you might only be one afternoon away
[1130.240-1131.830] from that work that you want done. And
[1131.840-1134.310] it's not because the models got magical.
[1134.320-1137.430] It's because actually orchestrating
[1137.440-1139.750] multi- aent systems has gotten simple
[1139.760-1141.830] enough that I can talk about this and
[1141.840-1143.990] share this and it's really very doable.
[1144.000-1145.750] And that's happened like really in the
[1145.760-1148.470] last 30 days or so. So have fun. Go jump
[1148.480-1150.630] into it and tell me what you build with
[1150.640-1152.310] your multi- aent system. I can't wait to
[1152.320-1155.320] hear
