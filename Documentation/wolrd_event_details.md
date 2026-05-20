This file will contain info on different world events that can proc for the game. Each entry will contain an ID to identify it, a more detailed description that can be provided to the user and then an short explanation of the effect.

id: orc_army
desc: "Rumours of this land's spoils and current instability due to your prescence have caused an Orcish raiding party to appear. Seeing your grand Citdel on the horizon they are making a rush for it in hopes of looting you domain."
effect: Spawn an 'Orcish Army' on one of the edge tiles that scales on the dragons level. It will head towards the citadel. If they reach it, lose all gold and citadel looses 1 HP. Army stats [Health:(400 + 10*level), Attack:(100 + 5*level), Defence:(50 + 5*level), Speed:15]

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