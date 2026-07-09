# Transcript: Combine Fable 5 & Sol 5.6 With This One Skill (Or Fall Behind)

State: Supporting evidence transcript (advisory research corpus)

- Video ID: `gsvZn4nbFus`
- URL: https://youtu.be/gsvZn4nbFus?si=1lsPv85aGjjS399g
- Channel: Chase AI
- Publish date: 20260708
- Duration seconds: 578
- Metadata language: `en-US`
- Caption language: `en-orig`
- Acquisition method: `captions_auto`
- Selection path: `en_us_en_orig_workaround`
- Quality note: machine-generated auto-captions; rolling-cue duplication removed by normalization, punctuation/segmentation may still be imprecise
- Content identity: `sha256:353be23548413e19839ce23abdad726c29df56beccd5d029c1e6cefbc8646731`

## Chapters

- 0.0: Intro
- 57.0: Sol & The Skill
- 321.0: Demo
- 567.0: Outro

## Normalized Transcript

[4.070-4.080] GPT 5.6 aka Soul is coming out tomorrow
[4.080-5.749] and the big question on everyone's mind
[5.759-8.470] is does this new model beat Claude
[8.480-10.629] Fable? Well, I think that's the wrong
[10.639-12.390] question to ask because instead of
[12.400-13.910] trying to figure out which one of these
[13.920-16.070] models is better, we should be asking
[16.080-18.150] how can we use these two powerful models
[18.160-20.070] together? And in today's video, I'm
[20.080-21.670] going to be giving you a skill that does
[21.680-24.070] exactly that. This skill includes a
[24.080-25.670] supercharged plan mode based on Matt
[25.680-27.509] PCO's Grill Me. We then have an
[27.519-29.189] adversarial planning session where
[29.199-30.870] Claude and Codex go headto-head till
[30.880-33.430] they come to a conclusion. Then once
[33.440-35.990] we're ready, we take that Fabled driven
[36.000-38.709] plan and hand it off to Codeex, which
[38.719-42.229] starting tomorrow will include Soul 5.6.
[42.239-44.549] After Codeex goes to work, then we have
[44.559-47.190] Fable review the entire process. All in
[47.200-48.549] all, we're not just getting the best of
[48.559-50.630] both of these models, we're also saving
[50.640-52.630] tokens in the aggregate versus having
[52.640-54.150] Fable do everything. So, I'm going to
[54.160-55.430] show you how this works. We're going to
[55.440-57.189] do a quick demo and then I'll be giving
[57.199-58.709] you the skill. So why should we even
[58.719-59.990] care about creating some sort of skill
[60.000-61.510] where Fable does most of the planning
[61.520-64.149] and then we pass it off to Soul 5.6?
[64.159-68.469] Well, first reason is Soul 5.6 is wildly
[68.479-69.990] powerful, at least according to the
[70.000-72.310] benchmarks. Now, grain of salt, this is
[72.320-74.390] coming from OpenAI, but when we look at
[74.400-77.990] Soul 5.6 Ultra and just standard 5.6 six
[78.000-80.149] soul. We see numbers on Terminal Bench
[80.159-83.670] 2.1 that put it ahead of Claude Mythos,
[83.680-85.830] let alone Fable 5. The second reason is
[85.840-88.230] token efficiency. There is a real reason
[88.240-90.550] why you see so much content around, hey,
[90.560-93.270] how can we reduce Fable's usage and the
[93.280-95.270] types of things you see are like advisor
[95.280-97.109] mode. You know, essentially having Fable
[97.119-99.429] plan and have Opus execute. Well, why
[99.439-101.910] have Opus execute if with at the same
[101.920-105.510] price I could have 5.6 do it or 5.5 do
[105.520-107.670] it? Point is, we're doing that same
[107.680-110.069] construct but with a better model and
[110.079-112.550] arguably a cheaper model than Opus. When
[112.560-115.030] we look at 5.6, it is more token
[115.040-117.590] efficient than 5.5 which was more token
[117.600-119.990] efficient than Opus 4.6. And we can see
[120.000-121.670] that in the data. What we're looking at
[121.680-125.270] right here is GPT 5.5 on extra high. Its
[125.280-129.589] pass rate on this benchmark was 23% at
[129.599-135.030] $1.24. When I look at 5.6, six, it's 25%
[135.040-138.390] score, so higher score at 56. So way
[138.400-139.990] cheaper and therefore way more
[140.000-141.589] efficient. And when we look at direct
[141.599-144.949] comparisons of 5.5 versus Opus 4.8,
[144.959-147.510] there's really no contest. Higher pass
[147.520-150.070] rates, lower cost. So we're essentially
[150.080-151.990] taking that same idea and just ramping
[152.000-154.070] it up with this 5.6 improvement. So how
[154.080-155.830] does this skill actually work? Well, I
[155.840-157.750] actually have a couple skills for you.
[157.760-159.990] In a vacuum, we have the codeex build
[160.000-161.589] skill. This is the idea that you created
[161.599-163.270] a plan with Fable and Codex is just
[163.280-164.229] going to go ahead and build that
[164.239-166.070] particular feature or particular
[166.080-168.630] product. I also have included an updated
[168.640-170.790] grillme codeex. Now, I've done a video
[170.800-172.550] on this skill before and what we've done
[172.560-177.030] is we've added on this idea of GPT 5.6
[177.040-178.630] actually going out there and building
[178.640-181.190] things for us. And so, when we look at
[181.200-183.750] the more comprehensive GMI codeex, which
[183.760-186.630] is the big skill, it occurs in four
[186.640-189.350] stages. The idea is you have some sort
[189.360-190.790] of project, some sort of feature you
[190.800-192.149] want to start and you kick it off with
[192.159-193.670] grill me codeex and the first thing that
[193.680-195.990] happens is an interview. This interview
[196.000-198.229] is literally the grill me skill from
[198.239-200.229] Matt PCO. So it is a plan mode on
[200.239-202.229] steroids. It goes way way deeper than
[202.239-204.070] Claude Code normally would. And we do
[204.080-207.030] this with Fable. All right. So Fable's
[207.040-209.910] driving the ship here. Secondly, we have
[209.920-212.309] adversarial planning. So Fable's come up
[212.319-214.710] with a plan. We then take that Fable
[214.720-217.990] plan and we push it over to Codeex. Now,
[218.000-219.350] in today's video, that's going to be
[219.360-222.789] 5.5, but tomorrow that will be 5.6. And
[222.799-225.030] Fable and Codex go back and forth for a
[225.040-227.270] maximum of five iterations where Fable
[227.280-228.789] says, "Hey, here's the plan." Codex
[228.799-230.710] says, "Okay, looks good. Accept X, Y,
[230.720-233.509] and Z." Then Fable says, "Uh, I agree, I
[233.519-234.630] disagree." And they go back and forth
[234.640-236.630] till they reach a consensus. Now once
[236.640-238.390] they reach that consensus and this is
[238.400-241.110] where the upgrades happen is we now push
[241.120-244.550] the actual build to codeex to 5.5 today
[244.560-247.589] and 5.6 tomorrow. I think this is way
[247.599-250.550] better than passing things off to Opus
[250.560-252.470] or to Sonnet or using advisor mode
[252.480-254.229] inside of cloud code because these GPT
[254.239-256.629] models are just better than those
[256.639-258.469] smaller anthropic models and they are
[258.479-261.030] cheaper. So, it really is a scenario
[261.040-263.670] where unless you just are super anti-GPT
[263.680-265.270] and anti-codex, it's hard to argue
[265.280-268.310] otherwise, especially if we get to a
[268.320-269.909] place where Fable is like kind of off
[269.919-271.830] the market. And lastly, once Codeex
[271.840-273.270] finishes the build, Fable is going to
[273.280-275.350] come in and it's going to review what it
[275.360-276.870] did and it's going to go through a
[276.880-279.270] maximum of two sort of iterations where,
[279.280-281.110] let's say, Fable thinks Codex did
[281.120-281.990] something wrong. It's going to say,
[282.000-283.749] "Hey, Codex, you did that wrong. Fix
[283.759-285.830] it." It's going to do that twice. If by
[285.840-287.270] the third time it's not complete, well
[287.280-289.670] then Fable will clean it up itself. So
[289.680-292.550] this is the process by which I think we
[292.560-295.189] get the best of OpenAI and Anthropic.
[295.199-297.030] Now before we hop into the demo, a quick
[297.040-299.430] word from today's sponsor, me. So I just
[299.440-300.710] released my Cloud Code master class
[300.720-302.469] inside of Chase AI plus and it is the
[302.479-304.230] number one way to go from zero to AI
[304.240-305.909] dev, especially if you don't come from a
[305.919-307.670] technical background. I update this
[307.680-309.990] every single week. We focus on real use
[310.000-312.710] cases and it also includes a codeex
[312.720-315.189] masterass as well. So, if you want to
[315.199-316.790] get a little bit more serious about AI
[316.800-318.390] and you have no idea where to begin,
[318.400-319.990] this is the place for you. There will be
[320.000-321.909] a link in the pin comment. Now,
[321.919-323.350] installing and using the skill is pretty
[323.360-324.469] straightforward. I will put a link to
[324.479-326.310] the GitHub in the description. Now, to
[326.320-327.110] use this, we're just going to do
[327.120-329.990] for/grill codeex. And we just give it
[330.000-331.350] our prompt what it is we're trying to
[331.360-333.029] build. So, we're trying to build trip
[333.039-335.590] atlas, which is a stylized cinematic
[335.600-337.350] trip planner web app. And I go into a
[337.360-338.710] little bit more details about what I
[338.720-339.830] want it to be, right? I want it to look
[339.840-341.189] kind of cool. I can put in the different
[341.199-343.270] places I'm going, all that. And once I
[343.280-344.629] do this, what's going to happen is it's
[344.639-346.469] going to kick off the grill me section
[346.479-347.909] of the plan, which if you're familiar
[347.919-350.469] with Matt PCO's work, it essentially is
[350.479-352.469] just a plan mode on steroids. It's going
[352.479-354.150] to ask me like 8 n 10 different
[354.160-356.150] questions. I go a lot deeper than your
[356.160-357.830] standard plan mode stuff. So, it's
[357.840-359.350] asking me what is this for? We're going
[359.360-361.909] to say this is for a real personal tool,
[361.919-364.070] not just a video demo. And for each of
[364.080-365.189] these, it also gives its
[365.199-367.110] recommendations. So, if you're confused
[367.120-368.790] about what I should choose and why,
[368.800-370.710] that's all spelled out for you. Now it's
[370.720-372.469] asking about geocoding and it's going to
[372.479-373.909] continue to go down these series of
[373.919-375.350] questions until it's happy with what
[375.360-377.670] we're creating. Now I'm going to skip
[377.680-378.629] through the rest of the questions
[378.639-380.070] because you can imagine what the next
[380.080-381.749] seven or eight questions will look like
[381.759-384.309] and we'll move into the adversarial
[384.319-385.749] planning stage. So we can see here it's
[385.759-387.270] written the plan and it also creates a
[387.280-389.029] markdown file where it logs all the back
[389.039-391.990] and forth between codeex and cloud code.
[392.000-394.150] And so right now we are on round one
[394.160-396.710] where it's passing it off to GBT. And so
[396.720-398.230] you can see them kind of going back and
[398.240-401.510] forth here on the log. But in this case,
[401.520-404.230] it only took them two rounds before it
[404.240-406.550] was approved. And so we can see what the
[406.560-409.110] two acts improved. You know, lock the
[409.120-411.270] identity, a real person tool, kind of
[411.280-413.029] what's going to be the actual sort of
[413.039-416.070] stack. And then it had 12 findings in
[416.080-417.749] the second round related to like
[417.759-419.830] hardening the data core. Now once it's
[419.840-421.189] completed this back and forth, you have
[421.199-423.830] a few options. either Codex is going to
[423.840-425.749] build it. Kind of what we've talked
[425.759-427.110] about from the beginning. We have the
[427.120-428.550] option just having Claude build it. So
[428.560-429.909] for whatever reason like I don't want to
[429.919-432.469] bring GPT in, you can keep it with Fable
[432.479-434.309] or you can stop here. But we're going to
[434.319-436.629] go ahead and let Codeex build this. And
[436.639-438.390] again, we can kind of go back and forth.
[438.400-440.710] If you think, well, GPT 5.6 is going to
[440.720-443.350] be better than Fable or 5.5 versus Opus
[443.360-445.990] 4.8. At the end of the day, the real
[446.000-447.749] value that can't really be argued with
[447.759-450.230] is going to be the token efficiency,
[450.240-453.510] especially if 5.6 6 is even close to
[453.520-455.029] what the benchmarks are claiming. So
[455.039-457.510] Codeex has finished up its build and you
[457.520-459.589] can see now what's happening is the
[459.599-461.510] review stage. So now Fable is going
[461.520-463.589] through everything Codex has built and
[463.599-465.029] then it's going to go back to Codex and
[465.039-466.629] say this is wrong, this was right.
[466.639-468.230] Remember it'll do two iterations of that
[468.240-470.390] before it's like hey I want to drive.
[470.400-472.230] It'll take the wheel and it will start
[472.240-474.150] writing the code itself. Now Fable is
[474.160-476.309] done with its review. It said there were
[476.319-478.070] a couple deviations which it felt were
[478.080-479.830] all reasonable. goes over the files and
[479.840-481.270] all this and now it's asking, hey, do
[481.280-482.309] you want to commit or you want to take a
[482.319-483.670] look at it? So, let's take a look at
[483.680-485.830] what it actually built. And so, here's
[485.840-488.390] what we got. So, over here we have sort
[488.400-490.070] of a map of the world and it looks like
[490.080-492.790] it created some custom graphics using
[492.800-495.270] the GPT image generator. So, you're able
[495.280-497.110] to like name the trip, you can add
[497.120-499.589] stops. Over here on the left, you can
[499.599-501.589] put where you're going and then sort of
[501.599-503.510] like what you're going to do at those
[503.520-505.909] different locations. It also has this
[505.919-507.589] cinematic replay. And I'm just going to
[507.599-508.950] mute this. So, let's see what happens
[508.960-511.350] here.
[511.360-514.630] So, it looks like I'll move over here.
[514.640-516.709] You can see sort of this weird plane
[516.719-518.790] hopping from spot to spot, which it
[518.800-521.430] looks like it created as an SVG. There's
[521.440-524.070] a little passport stamps and boom, there
[524.080-527.030] we go. So, you know, there's a lot we
[527.040-529.509] could do here to kind of make it look, I
[529.519-532.790] think, better, but in general, it built
[532.800-534.710] what we said we wanted to, right? Like
[534.720-536.790] everything actually works here. You
[536.800-538.470] know, if I delete things on here, delete
[538.480-541.110] some. I can move them up, down. I can
[541.120-543.670] change stuff. Let's say we added Tokyo.
[543.680-546.150] All of a sudden, it actually shows how
[546.160-547.910] far away that stop is. That's
[547.920-550.949] interesting. If I add that to the route.
[550.959-553.910] There we go. So, you know, actually
[553.920-555.430] built this out. I think it'd be a good
[555.440-557.110] not bad, I think, for the first pass.
[557.120-558.470] And what this really was about was just
[558.480-561.190] showing this workflow in action. And you
[561.200-562.790] can also see down here in terms of our
[562.800-565.110] usage, we only burned up about 130,000
[565.120-567.030] tokens on the fable side to get this
[567.040-568.630] whole thing done. So that's the skill in
[568.640-569.750] action. Hopefully you get a ton of use
[569.760-572.630] out of this one's 5.6 drops. As always,
[572.640-574.230] let me know what you thought about this
[574.240-575.350] video in the comments. Make sure to
[575.360-579.680] check out Chase AI Plus and I'll see you
