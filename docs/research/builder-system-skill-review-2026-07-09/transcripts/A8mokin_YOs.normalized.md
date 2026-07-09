# Transcript: New Skills! v1.1 brings /wayfinder, /research, /implement, /to-spec, /to-tickets

State: Supporting evidence transcript (advisory research corpus)

- Video ID: `A8mokin_YOs`
- URL: https://youtu.be/A8mokin_YOs?si=n2SAximDZwDd-IET
- Channel: Matt Pocock
- Publish date: 20260708
- Duration seconds: 911
- Metadata language: `en`
- Caption language: `en`
- Acquisition method: `captions_auto`
- Selection path: `pipeline_selector`
- Quality note: machine-generated auto-captions; rolling-cue duplication removed by normalization, punctuation/segmentation may still be imprecise
- Content identity: `sha256:a507447a824d1cbb8c8530f4155c10b3e8002b354ab4716ced99651edd28cee4`

## Chapters

- 0.0: v1.1 Is Ready!
- 37.0: to-spec, /to-tickets
- 154.0: Grilling skill improvements
- 246.0: Complete development lifecycle flow
- 405.0: Code review with refactoring smells
- 472.0: Introducing Wayfinder for large plans
- 681.0: Supporting skills: research and prototype
- 732.0: TDD skill updates
- 795.0: Migration guide and closing thoughts
- 839.0: AI Coding Crash Course announcement

## Normalized Transcript

[1.829-1.839] Hello friends. First video in a while
[1.839-3.990] and that is because I've been working on
[4.000-7.349] version 1.1 of my skills repo. It has an
[7.359-9.110] astonishing amount of stuff in there.
[9.120-11.669] There is an entire new approach to
[11.679-13.589] grilling which probably deserves its own
[13.599-14.950] video, but I'll try and squeeze it in
[14.960-18.070] here. There is a bunch of new changes to
[18.080-20.710] existing skills, including a rename of
[20.720-22.950] two main flow skills. There is just
[22.960-24.790] really way too much for me to summarize
[24.800-26.150] in this intro, so you're just going to
[26.160-27.670] have to watch the video to find out. We
[27.680-29.349] can see the PR is literally ready to
[29.359-31.990] merge now. So, why not? Let's actually
[32.000-33.670] freaking merge this thing. And just like
[33.680-37.190] that, we have our version 1.1 ready to
[37.200-38.630] go. Let's start with the two that are
[38.640-40.630] probably going to be most annoying for
[40.640-42.630] you and the most like why did he do
[42.640-45.110] this? And there is a very specific
[45.120-47.590] reason that I did it, which is that two
[47.600-50.069] skills have been renamed. For instance,
[50.079-53.350] two PRD has now been renamed to two
[53.360-55.590] spec. And if we go up one level, then we
[55.600-59.430] go to two uh issues has been renamed to
[59.440-61.270] two tickets. The reason I've done this
[61.280-63.029] is that this has just been bugging me
[63.039-65.189] for a long time. The thing that we were
[65.199-68.950] creating into PRD wasn't actually a PRD.
[68.960-71.109] It was a spec. A product requirements
[71.119-73.910] document kind of describes more things
[73.920-76.469] about the actual product itself, whereas
[76.479-79.190] we were allowing things to leak into the
[79.200-81.990] PRD that weren't necessarily PRDs. So
[82.000-83.830] for a long time I've wanted to rename it
[83.840-85.910] to to spec because that's what we were
[85.920-87.109] creating. We were just creating a
[87.119-89.510] specification. Specification is a much
[89.520-92.469] broader term that actually entails what
[92.479-94.310] we were building. A specification for a
[94.320-95.990] thing we want to build. That can be
[96.000-98.069] technical. It can be non-technical and
[98.079-99.429] it can blend the two. It doesn't really
[99.439-101.109] matter. When it came to two issues, two
[101.119-102.789] issues always felt like it was biased
[102.799-104.950] towards GitHub and linear that use
[104.960-107.830] issues. But really we want this to be
[107.840-109.910] tickets. you have a spec and then
[109.920-111.429] underneath the spec you have the tickets
[111.439-114.149] that are the journey that you uh take to
[114.159-115.990] actually enact the spec and create it.
[116.000-117.429] This has been annoying me for a long
[117.439-119.510] time and finally it no longer annoys me.
[119.520-121.350] It brings me joy. Now one irritating
[121.360-123.590] thing about this rename is that you will
[123.600-125.830] need to probably delete those skills and
[125.840-127.429] read them. This means you'll need to run
[127.439-130.550] npx skills add mapco skills. I'm pretty
[130.560-132.470] sure that this skills installer won't
[132.480-134.710] pick up the rename so it won't try to
[134.720-137.589] update to prd to turn it into tosp spec.
[137.599-138.949] You get what I mean? And so running this
[138.959-141.030] command is the safest way to grab all of
[141.040-142.710] these new skills cuz you get to just
[142.720-144.309] pick and choose which ones you want. And
[144.319-145.270] once you've done that, you should
[145.280-147.270] probably go through a pass through your
[147.280-149.910] skills folder and just check that uh no
[149.920-151.750] bad ones are still in there. So you want
[151.760-153.509] to make sure that you're intentionally
[153.519-155.270] grabbing all the right skills. The next
[155.280-157.270] change is that I've fixed a couple of
[157.280-159.030] bugs that people were having with grill
[159.040-161.030] me and grill with dogs. Both of them
[161.040-163.190] rely on this kind of central reference
[163.200-165.830] grilling skill that kind of show shows
[165.840-168.390] the LLM how to grill a person. I've
[168.400-170.070] sharpened up this line here saying
[170.080-171.750] asking multiple questions at once is
[171.760-174.710] bewildering even with this d direction
[174.720-177.030] to ask questions one at a time. It was
[177.040-179.589] still occasionally just going have
[179.599-181.990] multiple questions at once. So I've told
[182.000-184.550] it why we don't want uh multiple
[184.560-186.229] questions at once. We've also added a
[186.239-187.910] confirmation gate on the end. do not
[187.920-189.910] enact the plan until I confirm we've
[189.920-191.589] reached a shared understanding. Lots of
[191.599-192.710] people on different models were
[192.720-194.309] reporting that the grilling session
[194.319-196.309] would just end and then it would just go
[196.319-198.309] straight into implementation. So this is
[198.319-199.830] just an extra little gate there.
[199.840-202.710] Finally, on some situations, it would
[202.720-205.589] just grill itself, which is very very
[205.599-207.509] odd. Not something I've noticed or seen
[207.519-209.589] in my personal thing, but I I can only
[209.599-211.430] get a small subset of how these skills
[211.440-213.990] are actually used. So I've basically
[214.000-215.990] tried to use a couple of leading words
[216.000-218.229] to indicate the difference between facts
[218.239-220.869] and decisions. So sometimes it was using
[220.879-222.869] the previous phrasing here by just
[222.879-224.390] exploring the codebase and grilling
[224.400-225.830] itself. This was especially happening
[225.840-228.949] with fable actually. And so I've decided
[228.959-231.750] to make a distinction between facts. So
[231.760-233.589] facts that are things you find yourself
[233.599-235.990] by exploring the codebase and decisions.
[236.000-238.390] So decisions are needed to be made by
[238.400-239.670] the user. So, just a couple of
[239.680-241.190] sentences, added a couple of things
[241.200-242.949] changed around, and this has made it a
[242.959-244.309] lot more consistent. Definitely getting
[244.319-246.309] a lot fewer complaints about those weird
[246.319-247.589] issues happening. The next thing to say
[247.599-249.350] is that I've added a couple of skills
[249.360-252.630] that really just take the process that
[252.640-255.110] was primarily a planning process, didn't
[255.120-256.310] really hold your hand into
[256.320-259.189] implementation and turn it into a proper
[259.199-260.870] software development life cycle. So,
[260.880-262.550] many folks ask me, what is the flow?
[262.560-264.230] What is the main flow you're supposed to
[264.240-267.189] use with the skills? And first of all, I
[267.199-269.189] mean, this is it. We have number one,
[269.199-271.030] you're supposed to instead of using plan
[271.040-273.909] mode, you get an agent to grill you and
[273.919-276.390] it uses these couple of docs to add a
[276.400-278.550] glossery to kind of understand you
[278.560-280.469] better as you go along and also add
[280.479-282.150] architectural decision records so you
[282.160-284.310] can capture the non-obvious stuff. The
[284.320-285.909] stuff that goes in the grill for docs
[285.919-289.030] then goes into a spec as we saw before.
[289.040-290.870] That spec kind of defines the
[290.880-294.070] destination where you're going. Then you
[294.080-296.230] turn that spec into individual tickets
[296.240-298.150] so you can spread the development of it
[298.160-300.550] out over multiple agent sessions. That's
[300.560-302.550] the purpose of to tickets. You then
[302.560-304.629] implement each one of those tickets with
[304.639-306.790] a implement skill. And the implement
[306.800-309.350] skill is very very simple. It just looks
[309.360-311.029] like this. Implement the work described
[311.039-313.590] by the user in the spec or tickets. Use
[313.600-316.310] TDD where possible at pre-agreed seams.
[316.320-318.629] That's a nice one. And run type checking
[318.639-320.310] regularly. Single test files regularly.
[320.320-322.469] Full test sweep once at the end. Once
[322.479-324.790] done, use code review to review the work
[324.800-326.150] and then commit your work to the current
[326.160-328.150] branch. I almost didn't make a skill for
[328.160-330.390] this because it's really simple, right?
[330.400-332.550] It's just mostly relying on the agents
[332.560-334.950] prior on its, you know, on the harness
[334.960-337.189] kind of teaching it what to do. And I
[337.199-339.110] didn't honestly think we needed a skill
[339.120-341.029] here. But folks kept asking me what's
[341.039-343.189] the flow? What's the flow here? And so I
[343.199-344.870] figured just an implement skill, make it
[344.880-346.950] nice and simple, right? At each stage of
[346.960-348.710] the process, call this skill. So that
[348.720-350.710] means implement earns its place here
[350.720-352.629] because you know okay once we got two
[352.639-354.469] tickets then we just got to implement
[354.479-355.990] each ticket in a separate coding
[356.000-358.230] session. Implement then itself calls
[358.240-360.870] code review and code review I graduated
[360.880-363.830] this out of in progress on version one.
[363.840-365.990] So it's been around for a little bit but
[366.000-367.909] I have made some updates to it in this
[367.919-369.189] version two. The theory of the code
[369.199-371.670] review skill is that it reviews code on
[371.680-374.710] two axes. So it does a sub agent for
[374.720-376.550] each one of these. The first one is the
[376.560-378.950] standards axis. Does the code conform to
[378.960-381.510] this repo's documented coding standards?
[381.520-383.990] So, if you've got a coding standards.md
[384.000-386.150] file somewhere in your repo, then it
[386.160-388.550] will read that and check against those.
[388.560-390.309] I generally think that coding standards
[390.319-393.189] belong outside of your agents.md file.
[393.199-394.469] They're supposed to be somewhere
[394.479-396.790] separate and the code review point is
[396.800-399.270] where they're most useful. And then once
[399.280-400.629] you've done the standards, you then go
[400.639-402.790] on to the spec. Does the code faithfully
[402.800-405.189] implement the originating issue or PRD
[405.199-407.189] or spec? They both run as parallel sub
[407.199-410.150] agents and it does a process here where
[410.160-412.150] it walks through each part. Now the
[412.160-413.670] thing that's cool and new about this
[413.680-415.510] skill is that I've been reading Martin
[415.520-418.309] Fowler's Refactoring again. And what I
[418.319-420.870] decided to do is Martin Fowler names a
[420.880-423.830] bunch of different smells that the agent
[423.840-426.390] can identify in bad code. Refactoring is
[426.400-428.309] such an old book, such a well-sighted
[428.319-431.189] book that these uh kind of smells are
[431.199-433.430] deep in the agent's prior. And so all
[433.440-434.790] you need to do is kind of invoke the
[434.800-436.390] idea of okay mysterious name or
[436.400-438.070] duplicated code or feature envy data
[438.080-439.830] clumps primitive obsession repeated
[439.840-441.749] switches divergent change speculative
[441.759-443.990] generality message chains you see what I
[444.000-446.230] mean like these are all deep in the
[446.240-447.909] agent's kind of knowledge base and all
[447.919-449.830] we got to do is just really describe
[449.840-452.550] them in a sentence and what I found is
[452.560-454.870] that leads the word or leads the agent
[454.880-456.870] to repeat that word back to you and say
[456.880-459.029] yes I found some message chains I need
[459.039-461.189] to remove them I found a middleman
[461.199-463.189] situation I need to uh fix that. So, I
[463.199-464.469] tested this for a couple of weeks and it
[464.479-467.350] was outrageously useful. It was really,
[467.360-468.950] really nice at improving the quality of
[468.960-471.029] my code and it's really cheap to add
[471.039-473.189] here. Just kind of like 10 lines. But,
[473.199-474.950] let's go and talk about the one that I'm
[474.960-477.830] really really excited about, which is a
[477.840-480.869] whole new change to the way that we kick
[480.879-484.150] off and shape specs. So, the pre-spec
[484.160-486.550] bit. In other words, it goes here where
[486.560-489.510] it may in some situations replace Grill
[489.520-491.990] with Docs and it's called Wayfinder. I
[492.000-494.150] will make an entire post, entire video
[494.160-496.869] about WFinder, but uh suffice to say is
[496.879-499.510] that I would love for you in situations
[499.520-501.110] where you're thinking about using Grill
[501.120-504.150] with Docs instead to default to Wfinder
[504.160-506.150] instead. What Wayfinder does is it's
[506.160-508.629] designed for situations where you have a
[508.639-511.110] ton of stuff that you want to plan but
[511.120-513.670] and too big for one agent session. In
[513.680-515.029] other words, you're going to blow out of
[515.039-516.949] the smart zone of the agent or you might
[516.959-518.469] even blow out of the context window of
[518.479-520.469] the agent. You need to split it into
[520.479-522.310] multiple parts in order to figure out
[522.320-523.990] where you're going. A loose idea has
[524.000-525.670] arrived, too big for one agent session
[525.680-527.750] and wrapped in fog. The way from here to
[527.760-529.910] the destination isn't visible yet. This
[529.920-532.550] skill charts the way as a shared map on
[532.560-534.389] the repo's issue tracker, then works its
[534.399-536.230] tickets one at a time until the route is
[536.240-538.630] clear. These maps are saved in GitHub
[538.640-540.070] issues. For instance, this is one on the
[540.080-542.230] Sand Castle repo where we're doing a
[542.240-544.949] spike to think about maybe pulling in
[544.959-547.509] the AI SDK as a dependency. A big big
[547.519-549.590] change. And so you can see there are no
[549.600-552.150] decisions that have um been made so far
[552.160-554.230] and all of the decisions that need to be
[554.240-556.790] made are saved in sub issues and these
[556.800-559.590] sub issues have blocking relationships.
[559.600-561.590] So we can see that no decision can be
[561.600-564.230] made here before we make this key
[564.240-565.990] decision at the start. Each one of these
[566.000-569.030] decisions is scoped to be the size of an
[569.040-570.470] agent session. And we can see that
[570.480-572.470] they're labeled as different types here.
[572.480-574.310] So for instance, this one is labeled as
[574.320-576.790] a research task. So, this is really an
[576.800-579.350] AFK task for the agent to go off, do
[579.360-581.590] some research, and then come back. This
[581.600-583.350] one, I think, is a research as well.
[583.360-585.030] This one is a research task, and this
[585.040-587.829] one is a grilling task. So, this one
[587.839-589.590] needs a grilling session to be done
[589.600-592.070] here. I think these are all grillers. We
[592.080-593.670] can see these defined in the ticket
[593.680-595.509] types down here. So, we have research,
[595.519-598.630] we have grilling, we also have prototype
[598.640-600.870] as well. So this is something I've been
[600.880-603.110] really advocating for recently is doing
[603.120-605.430] more prototyping before you get to a
[605.440-607.430] spec. The idea is you raise the fidelity
[607.440-609.030] of the discussion by making a cheap
[609.040-611.269] rough concrete artifact to react to an
[611.279-613.990] outline rough take UI logic code via the
[614.000-615.750] prototype skill. We'll get to that in a
[615.760-617.750] minute. Links to the prototype as an
[617.760-619.750] asset. And it says use when how should
[619.760-621.990] it look or how should it behave is a key
[622.000-624.710] question. And this is essential for
[624.720-626.550] almost anything that touches front-end
[626.560-628.150] code. So I would definitely be
[628.160-630.310] recommending using Wfinder for anything
[630.320-631.829] that touches the front end. The final
[631.839-634.389] one here is just tasks. So config that
[634.399-636.790] needs to be set up um provisioning
[636.800-638.790] access, you know, moving data into the
[638.800-640.710] shape, you know, all the sort of boring
[640.720-642.310] stuff that doesn't need a grilling
[642.320-644.710] decision and can't really be automated
[644.720-647.030] by AI. What you end up with is after all
[647.040-649.190] of these tickets are closed, all of that
[649.200-651.750] information gets saved onto the map with
[651.760-653.829] the original tickets as kind of primary
[653.839-655.829] sources for what was captured. And you
[655.839-658.230] can then take this map and just turn it
[658.240-660.150] into a spec in the regular way. What
[660.160-661.750] I've found that instead of having the
[661.760-663.910] kind of anxiety of managing my session
[663.920-665.670] with Grill with Docs, having to hand
[665.680-667.750] off, worry about the smart zone, with
[667.760-669.829] Wayfinder, it's kind of all managed for
[669.839-672.230] me, I just get to close a session, open
[672.240-674.389] up the next Wayfinder ticket. It's all
[674.399-676.150] saved in GitHub, so it's collaborative.
[676.160-677.990] You can share it across your team. And
[678.000-679.350] once the map is done, once it's
[679.360-681.190] complete, you just go to to spec and
[681.200-682.389] you're good to go. To support the
[682.399-684.710] wayfinder skill, we have a new research
[684.720-687.430] skill which is very small, very handy
[687.440-689.430] for when you just need to do a research
[689.440-692.069] session or it kind of influences the
[692.079-693.910] model in researching in the right way as
[693.920-695.590] well or at least the way that I like.
[695.600-697.110] Spins up a background agent to do the
[697.120-698.470] research so you keep working while it
[698.480-700.230] reads. Investigate the question against
[700.240-701.910] primary sources. Write the findings to a
[701.920-703.829] simple markdown file and save it where
[703.839-705.750] the repo already keeps such notes match
[705.760-707.190] the existing convention. So this is
[707.200-708.790] useful too if you need to do any
[708.800-710.150] research. you can just invoke the
[710.160-711.910] research skill and you're good to go.
[711.920-713.590] The next one, of course, is the
[713.600-715.910] prototype, which I've kind of shown off
[715.920-717.190] a little bit before. I don't think I've
[717.200-719.030] done a full video on it. This is now
[719.040-721.030] model invoked so that Wayfinder can
[721.040-723.430] invoke itself and it essentially gives
[723.440-726.710] you a choice between logic or state. So,
[726.720-730.069] it's either a logic prototype or a UI
[730.079-732.069] prototype, and they react quite
[732.079-733.269] differently. The final change is
[733.279-734.710] something that people have been asking
[734.720-736.870] for for a while and I finally decided to
[736.880-738.629] pull the trigger on it which is before
[738.639-741.269] in my TDD skill it would recommend a set
[741.279-743.590] of steps for you to follow and that was
[743.600-745.750] a little bit awkward sometimes. the
[745.760-747.829] steps were like it would confirm what
[747.839-750.470] tests it wanted to write with you and
[750.480-752.230] then you would you know walk it through
[752.240-754.870] walk it through and it didn't fit with
[754.880-757.990] most people's uh idea of how TDD should
[758.000-760.069] work which is you should be able to pass
[760.079-763.190] an AFK agent the TDD skill and it should
[763.200-765.829] just work and so this TDD skill is now
[765.839-768.069] reference material only so it doesn't
[768.079-770.790] specify any particular steps apart from
[770.800-772.550] just the order in which you should write
[772.560-775.110] tests in so to do red green refactor so
[775.120-776.949] It just says red before green one slice
[776.959-779.670] at a time. And it also splits away uh
[779.680-782.629] refactoring as as not part of the loop.
[782.639-784.870] So it's no longer a red green refactor
[784.880-787.829] loop. It's more just red green. I tend
[787.839-790.310] to think that putting the refactoring in
[790.320-793.110] the code review part is a lot more
[793.120-794.470] productive because then you don't
[794.480-797.269] overload the implementation. So that is
[797.279-799.509] all of the changes that have come in on
[799.519-802.470] the skills. It is a lot of changes. And
[802.480-804.150] if you're nervous about missing any of
[804.160-805.910] the updates, then I recommend that you
[805.920-808.629] clear out all of your skills and do npx
[808.639-810.550] skills update and grab all of the new
[810.560-812.069] ones. If you've made updates to your
[812.079-813.430] skills in the meantime, then you can
[813.440-815.269] just point your clanker at my repo and
[815.279-817.110] just say pull down all of the good new
[817.120-818.710] stuff, especially pointing at the
[818.720-820.389] release notes. The thing I think this
[820.399-822.069] release will be remembered for is to
[822.079-823.829] spec and to tickets changing because
[823.839-825.430] that is just a little bit of friction,
[825.440-826.949] but I think good friction because it
[826.959-829.750] names it properly and I hope to be the
[829.760-831.269] start of you getting obsessed with
[831.279-832.949] Wfinder. I'm using Wayfinder for
[832.959-835.110] literally everything, even non-coding
[835.120-836.629] stuff. I've actually been planning my
[836.639-838.870] next course with Wfinder and it's
[838.880-840.389] really, really good. And in fact, why
[840.399-842.470] don't I just show you that course now?
[842.480-845.110] This is the AI coding crash course. This
[845.120-846.550] is going to be different from the
[846.560-848.629] cohorts that I usually run. It's going
[848.639-850.629] to be much much cheaper and it's going
[850.639-852.470] to be self-paced so you can purchase it
[852.480-854.629] anytime. You get help from the Discord
[854.639-856.230] kind of in the usual way, but it's not
[856.240-858.310] going to be gated like a normal cohort.
[858.320-861.110] It is going to be the perfect intro for
[861.120-863.110] anyone who's looking to get into AI
[863.120-865.509] coding whether you are a developer or
[865.519-867.509] whether you are not a developer. So for
[867.519-869.030] senior engineers, it's going to be a
[869.040-871.269] conversion course. For folks who are new
[871.279-873.110] to development, it's going to be the way
[873.120-874.949] that you can actually get productive
[874.959-876.790] using these crazy new tools. I've not
[876.800-878.629] announced a price yet. I am going to
[878.639-880.949] just be adding signups in here and it
[880.959-882.790] will be available once I finish filming
[882.800-885.509] it. Maybe in about uh August time I
[885.519-887.030] think. But folks, thank you so much for
[887.040-888.389] watching. It's always a pleasure sharing
[888.399-890.629] these skills updates with you. It is
[890.639-892.949] really cool to see the usage just
[892.959-894.790] absolutely grow and grow. Everyone tells
[894.800-896.389] me I shouldn't show the star count, but
[896.399-899.110] it's up to like 160k stars now. There
[899.120-901.750] are 7 million downloads on Skills.sh. It
[901.760-903.750] is just bonkers. So, thank you so much
[903.760-906.310] for enjoying the skills. I hope they are
[906.320-908.069] helping you ship more and ship more
[908.079-911.920] productively and I will see you very
