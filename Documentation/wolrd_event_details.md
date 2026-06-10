This file will contain info on different world events that can proc for the game. Each entry will contain an ID to identify it, a more detailed description that can be provided to the user as flavour text and then an short explanation of the effect.

id: raider_army
desc: "Rumours of this land's spoils and current instability due to your prescence have caused a mercenary raiding party to appear. Seeing your grand Citdel on the horizon they are making a rush for it in hopes of looting you domain."
effect: Spawn an 'Raider Army' on one of the edge tiles that scales with the dragons level. It will head towards the citadel. If they reach it, lose all gold and citadel looses 1 HP. Army stats [Health:(400 + 10*level), Attack:(100 + 5*level), Defence:(50 + 5*level), Speed:15]

id: storm_winds
desc: "Rough storm clouds roll in causing thunder and lightning to echo across the land. Howling winds rip through the air, buffeting you as you fly and making it difficult to travel."
effect: For the rest of the day, -50% speed for the dragon, rounded up

id: town_militia
desc: "All the settlements in the land have rallied their militia for a short time. Their citizens line the walls and bear makeshift weapons, ready to protect their homes in these troubled times."
effect: settlements deal 10% more damage and take 10% less for the day

id: settlement_investments
desc: "The settlements of the lands have decided to invested extra spending into improving their homeland, fortify their settlements and building more infastructure."
effect: If a settlement will grow at the end of the day, double the values gained. If a settlement heals it heals twice as much.

id: snowfall
desc: "Heavy snow blankets the lands, coating the ground in a layer of white and freezing rivers. The human armies struggle to trudge through the thick snowfall, drastically slowing them down, however perhaps new routes have opened up to them."
effect: Armies have their move speed reduced by 50% but can path over rivers for this turn. They cannot however finish on a river tile.

id: heatwave
desc: "The sun burns bright today, bathing your domain is harsh light and high temperatures. The heat helps enhance your fire, granting it additional power to burn your foes."
effect: The Dragon deals an additinal 15% damage for the rest of the day

id: heavy_rain
desc: "The clouds are dark and rain falls hard and heavy. The water coating everyting makes it harder to burn, but the settlements below rejoice as their crops are well provided for, drinking from the damp earth.
effect: Dragon deals -15% damage for today and settlements eco growth is 150% of normal for this turn.

id: arcane_fog
desc: "Strange fog cloaks the land as tendrils of mist snake over the hills and through the forests, obscuring everything below. Otherworldy noises come from the fog that dont quite sound right and its as if the land is moving. You find it difficult to see anything around you and the fog extends to your mind, removing even the memories of the landscape below. What could be causing this?"
effect: reapply the fog of war to the whole map just like it is at the start of the game.

id: citadel_vigor
desc: "The ancient magic of your home stirs, pleased by all the spoils you have returned with to add to your treasure trove. Roots sprout from the ground, wrapping around cracked bricks and strenghtening them. Earth and stone meld into open holes in the walls left by attacks, forming new natural surfaces. Thorns and thickets sprout up around the ground further protecting your home and renewing its structure."
effect: Citadel heals 1 HP. If max HP nothing happens.

id: golden_caravan
desc: "A wealthy merchant caravan has been spotted crossing through the land, its wagons laden with gold and exotic goods. They travel with a small guard escort, but their riches glitter in the sunlight, practically begging to be claimed. Of course, raiding them may draw the ire of distant kingdoms who funded the expedition."
effect: Spawn a 'Golden Caravan' unit on a random edge tile that moves toward the opposite edge. If the Dragon defeats it, gain gold equal to (200 + 20*level) and a "Revenge Army" (Raider Army) spawns at the edge of the map to punish the Dragon's greed. If the caraca  escapes off the map edge, nothing happens. Caravan stats [Health:(150 + 5*level), Attack:(50 + 5*level), Defence:(80 + 5*level), Speed:10]

id: earthquake
desc: "The ground shakes violently as a tremor ripples across the land. Buildings crack, walls crumble, and great fissures tear open across roads and pathways. The settlements scramble to repair the damage while armies in the field struggle to maintain formation on the shifting earth."
effect: All settlements lose 10% of their current health (rounded down, minimum 1 damage). All armies currently on the map have their speed reduced by 25% for the day. Any settlement that was about to grow delays its growth by one day.

id: dark_eclipse
description: "A black shroud envelops the sun casting dark shadows everywhere"
effect: Half of the Dragons flight range for the day and everything outside of the flightrange is rendered as a black tile