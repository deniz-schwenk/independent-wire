# Hantavirus outbreak on MV Hondius cruise ship triggers international health alerts

**Configuration:** T = 0.50, V = V2  
**Date:** 2026-05-11 · bundle topic-04  
**Slug:** clean-hantavirus

## Topic

> Passengers evacuated from the MV Hondius to the US and France have tested positive for hantavirus, prompting the World Health Organization to monitor the situation. Health authorities in multiple countries are implementing tracking measures as more cases emerge from the vessel.

- Original `source_count` (production, T=0.30 V1): **65**
- Audit labels: on = **56**, off = **9**, total = **65**, baseline off % = **13.8%**

## At this configuration (T = 0.50, V = V2)

- Retained (sim ≥ 0.50): **33** of 65
- Dropped: **32**
- On-topic retained: **33** / 56 (recall = **0.589**)
- Off-topic retained: **0** (off % of retained = **0.0%**, precision = **1.000**)

## Findings

Sorted by similarity descending. **Kept** = sim ≥ threshold (assigned at this config). **Drop** = sim < threshold (would orphan or move to another topic). The audit `label` and `reasoning_note` are unchanged across configs — they describe the finding, not the cut.

| # | sim | kept | label | lang | outlet | title | reasoning |
|---:|---:|:--:|:--:|:--|:--|:--|:--|
| 1 | 0.762 | yes | on | es | Clarin | Brote de hantavirus en el crucero MV Hondius hoy, EN VIVO: número de contagios, la cepa An | Brote hantavirus MV Hondius live cepa Andes contagios — direct |
| 2 | 0.730 | yes | on | en | Financial Times | Two cruise ship evacuees test positive for hantavirus | Two cruise ship evacuees test positive for hantavirus US France — direct |
| 3 | 0.721 | yes | on | vi | VnExpress | Pháp phát hiện ca Hantavirus đầu tiên lây từ ổ dịch tàu Đại Tây Dương | Pháp ca Hantavirus đầu tiên ổ dịch tàu Đại Tây Dương Rist — direct |
| 4 | 0.696 | yes | on | de | Tagesschau | Kreuzfahrtschiff: Zwei weitere Passagiere positiv auf Hantavirus getestet | Kreuzfahrtschiff zwei weitere Hantavirus positive Französin — direct |
| 5 | 0.660 | yes | on | en | Guardian World | Hantavirus cruise ship passengers enter isolation facility after evacuation to UK | Hantavirus cruise ship passengers isolation facility UK Merseyside — direct |
| 6 | 0.650 | yes | on | en | Guardian World | ‘It was either this or the pool’: hantavirus ship becomes latest Tenerife tourist attracti | Hantavirus ship MV Hondius Tenerife tourist attraction Canary — direct |
| 7 | 0.650 | yes | on | en | Politico Europe | One American has tested positive for hantavirus, another has mild symptoms | One American tested positive other mild hantavirus flight 17 — direct |
| 8 | 0.648 | yes | on | en | UN News | Passengers leave hantavirus-hit cruise ship in Tenerife as WHO says outbreak ‘not another  | Passengers leave hantavirus-hit cruise ship Tenerife WHO — direct |
| 9 | 0.643 | yes | on | en | DW News | Hantavirus: Evacuated passengers begin returning home | Hantavirus Evacuated passengers begin returning home Germany — direct |
| 10 | 0.637 | yes | on | de | Der Spiegel | Hantavirus: Was gegen eine Pandemie spricht – und wo die Risiken liegen | Hantavirus was gegen Pandemie spricht MV Hondius — direct |
| 11 | 0.636 | yes | on | ru | Novaya Gazeta Europe | «Вирусам наплевать на политику, и они не уважают границы». На Тенерифе приняли лайнер, где | MV Hondius Тенерифе Гранадилья хантавирус вспышка — direct |
| 12 | 0.635 | yes | on | de | Tagesschau | Hantavirus-Verdacht auf Atlantikinsel - Hilfe kommt per Fallschirmsprung | Hantavirus-Verdacht Atlantikinsel Fallschirmsprung Hondius — direct |
| 13 | 0.630 | yes | on | ru | Meduza | У пассажиров из Франции и США, эвакуированных с круизного лайнера, обнаружили хантавирус | Пассажиры Франции США Хондиус хантавирус AP — direct |
| 14 | 0.629 | yes | on | en | South China Morning Post | More passengers from hantavirus-hit cruise ship test positive | More passengers hantavirus-hit cruise ship test positive French American — direct |
| 15 | 0.617 | yes | on | en | Guardian World | Evacuated US and French MV Hondius passengers test positive for hantavirus | Evacuated US French MV Hondius passengers test positive — direct |
| 16 | 0.599 | yes | on | es | El Financiero | Evacúan a pasajeros del crucero afectado por hantavirus: Inicia repatriación con medidas e | Evacúan pasajeros crucero hantavirus repatriación Madrid hospital — direct |
| 17 | 0.599 | yes | on | en | BBC World | Tourist hotspot at 'end of the world' denies causing hantavirus outbreak | Tourist hotspot end of the world denies hantavirus outbreak Ushuaia — direct |
| 18 | 0.597 | yes | on | en | Dawn | US, French nationals from hantavirus ship test positive | US French nationals from hantavirus ship test positive — direct |
| 19 | 0.595 | yes | on | tr | Hurriyet | Hantavirüs semptomları tahliye edilen yolcular arasında yayılıyor: DSÖ alarma geçti! ABD v | Hantavirüs semptomları tahliye yolcular DSÖ alarma — direct |
| 20 | 0.590 | yes | on | en | RT | US decision on hantavirus-hit ship passengers ‘may have risks’ – WHO chief | US decision hantavirus-hit ship passengers risks WHO chief — direct |
| 21 | 0.585 | yes | on | en | Yonhap | N. Korea flags hantavirus danger amid cruise ship outbreak | N Korea flags hantavirus danger amid cruise ship outbreak — direct |
| 22 | 0.571 | yes | on | en | Ukrinform | Ukraine records dozens of hantavirus cases each year – Public Health Center | Ukraine records dozens of hantavirus cases each year Public Health — direct |
| 23 | 0.568 | yes | on | en | Indian Express | 2 Indians aboard cruise ship with hantavirus cases evacuated to Netherlands | 2 Indians aboard cruise ship hantavirus cases Netherlands — direct |
| 24 | 0.562 | yes | on | tr | Hurriyet | Hantavirüs tahliyesi | Hantavirüs tahliyesi Tenerife kruvaziyer yolcular — direct |
| 25 | 0.548 | yes | on | en | NPR | U.S. cruise passengers arrive in the U.S. after one tests positive for hantavirus | US cruise passengers arrive hantavirus mildly positive French — direct |
| 26 | 0.544 | yes | on | de | Tagesschau | Wie läuft die Evakuierung der "Hondius" ab? | Evakuierung Hondius Teneriffa Passagiere Crew — direct |
| 27 | 0.540 | yes | on | en | Al Jazeera | Two more cruise ship passengers test positive for hantavirus | Two more cruise ship passengers test positive hantavirus French American — direct |
| 28 | 0.528 | yes | on | es | El Pais | Última hora del brote de hantavirus, en directo \| Sanidad informa de que finalmente los pa | Última hora brote hantavirus Sanidad pasajeros cuarentena — direct |
| 29 | 0.525 | yes | on | es | El Tiempo | El pueblo de la Patagonia argentina donde el hantavirus es una amenaza constante desde hac | Pueblo Patagonia hantavirus amenaza desde hace crucero Argentina — direct background |
| 30 | 0.522 | yes | on | en | Japan Today | Evacuation flights leave Tenerife after cruise ship virus outbreak | Evacuation flights leave Tenerife cruise ship virus outbreak — direct |
| 31 | 0.522 | yes | on | tr | Hurriyet | Ölüm gemisinde yeni sır: Hantavirüs gemiye nereden geldi? | Ölüm gemisinde MV Hondius Hantavirüs nereden — direct |
| 32 | 0.511 | yes | on | en | BBC World | US and French nationals test positive for hantavirus after leaving ship | US French nationals test positive hantavirus after leaving ship Nebraska — direct |
| 33 | 0.507 | yes | on | pt | Agencia Brasil | Passageiros começam a deixar navio onde houve surto de hantavírus | Passageiros começam deixar navio MV Hondius surto hantavírus — direct |
| 34 | 0.488 | no | on | es | El Pais | Fernando Simón con Mónica García y con Ana Mato: esta crisis no es como la covid, sino com | Fernando Simón hantavirus comparación covid sangre — direct |
| 35 | 0.487 | no | on | it | ANSA | Una francese positiva all'hantavirus, sintomi peggiorati dopo viaggio di rientro | Una francese positiva all'hantavirus sintomi peggiorati primo caso Francia — direct |
| 36 | 0.484 | no | on | en | CNA | US, French nationals from hantavirus ship test positive | US French nationals hantavirus ship test positive Dutch couple German woman died — direct |
| 37 | 0.476 | no | on | en | Anadolu Agency | Last evacuation flights for passengers of hantavirus-hit cruise ship to depart Monday | Last evacuation flights hantavirus-hit cruise ship Monday 94 — direct |
| 38 | 0.473 | no | on | de | Tagesschau | Deutsche Passagiere der "Hondius" auf dem Weg in die Heimat | Deutsche Passagiere Hondius auf dem Weg in die Heimat — direct |
| 39 | 0.473 | no | on | es | El Pais | Bloqueo del tratado de pandemias en la OMS en plena crisis del hantavirus | Bloqueo tratado pandemias OMS plena crisis hantavirus — direct |
| 40 | 0.450 | no | on | es | Infobae | Llegan a Alemania cuatro pasajeros sin síntomas evacuados del crucero HV Hondius | Llegan Alemania cuatro pasajeros sin síntomas crucero HV Hondius — direct |
| 41 | 0.447 | no | on | en | BBC World | French national shows symptoms on return from hantavirus-hit ship | French national shows symptoms return hantavirus-hit ship Paris quarantine — direct |
| 42 | 0.447 | no | on | en | RT | British army parachutes hantavirus response team to remote island (VIDEO) | British army parachutes hantavirus response team remote island — direct |
| 43 | 0.445 | no | on | en | Anadolu Agency | French passenger develops symptoms after evacuation from hantavirus-stricken cruise ship | French passenger develops symptoms after evacuation hantavirus cruise — direct |
| 44 | 0.441 | no | on | vi | VnExpress | Vận tải cơ Anh vượt 3.000 km, thả lính điều trị ca nghi nhiễm Hantavirus | Vận tải cơ Anh 3000km lính điều trị Hantavirus Đại Tây Dương — direct |
| 45 | 0.435 | no | on | es | Infobae | España resalta la coordinación ante el hantavirus al agradecer a Guterres su apoyo | España coordinación hantavirus agradecer Guterres — direct |
| 46 | 0.432 | no | on | en | South China Morning Post | Hong Kong leverages ‘unrivalled’ medical hub status amid global hantavirus alarm | Hong Kong medical hub global hantavirus alarm pandemic preparedness — direct |
| 47 | 0.429 | no | on | en | Le Monde | Hantavirus: After first positive case in France, government aims to 'break chain' of trans | Hantavirus first positive France break chain transmission five French — direct |
| 48 | 0.424 | no | on | en | NDTV | "Family Table Was Left Empty": Hantavirus Renews Memories Of 2018 Outbreak | Family Table Empty hantavirus 2018 outbreak Mailen Valle — direct background |
| 49 | 0.406 | no | on | en | AllAfrica | South Africa: How an SA Team of Scientists Hunted a Rare Hantavirus Strain | South Africa team scientists hunted rare hantavirus strain — direct |
| 50 | 0.400 | no | on | en | DW News | Endemic, epidemic, pandemic: What's the difference? | Endemic epidemic pandemic difference Andes hantavirus outbreak — direct |
| 51 | 0.386 | no | on | en | South China Morning Post | Paratroopers jump onto Britain’s most remote inhabited island for hantavirus mission | Paratroopers Britain's most remote island hantavirus mission — direct |
| 52 | 0.357 | no | off | en | NDTV | Middle East Conflicts Pose A Danger To Whales Off South Africa: Study | Middle East Conflicts danger to Whales South Africa |
| 53 | 0.355 | no | on | es | Infobae | Sánchez resalta la coordinación ante el hantavirus al agradecer su apoyo a Guterres | Sánchez resalta coordinación hantavirus agradecer Guterres — direct |
| 54 | 0.331 | no | on | es | Infobae | La mujer ingresada en Alicante por sospechas de hantavirus se hará hoy una tercera PCR | Mujer ingresada Alicante sospechas hantavirus tercera PCR — direct |
| 55 | 0.330 | no | on | es | Infobae | Cuatro alemanes evacuados del 'MV Hondius' llegan a un hospital de Fráncfort para someters | Cuatro alemanes evacuados MV Hondius hospital Fráncfort — direct |
| 56 | 0.329 | no | off | en | CrisisWatch (ICG) | On Our Radar | CrisisWatch ICG On Our Radar weekly |
| 57 | 0.327 | no | off | es | El Financiero | ¿Te falta el aire? Así afecta el asma a los pulmones; estas son las señales de una crisis  | Te falta el aire asma pulmones crisis señales |
| 58 | 0.310 | no | off | en | CNA | Indonesia warns of becoming hub for transnational cybercrime networks following Jakarta, B | Indonesia warns hub transnational cybercrime Jakarta Batam |
| 59 | 0.309 | no | off | de | Der Spiegel | Straße von Gibraltar: Grindwale schreien gegen Schiffslärm an | Straße von Gibraltar Grindwale Schiffslärm Staubsauger |
| 60 | 0.307 | no | off | es | El Pais | Las ballenas alzan la voz para hacerse oír entre el ruido de los barcos y no lo logran | Ballenas calderones Gibraltar ruido barcos decibelios |
| 61 | 0.284 | no | on | en | Politico Europe | France enforces strict measures after citizen tests positive for hantavirus | France strict measures after citizen tests positive hantavirus flight — direct |
| 62 | 0.269 | no | off | pt | Folha de S.Paulo | Coordena��o de mensagens no WhatsApp ataca Anvisa e defende Yp� | Coordenação mensagens WhatsApp ataca Anvisa Ypê |
| 63 | 0.242 | no | on | pt | Folha de S.Paulo | Teste de americano que estava em cruzeiro d� positivo para hantav�rus | Teste americano cruzeiro positivo hantavírus 17 americanos — direct |
| 64 | 0.241 | no | off | vi | VnExpress | Nam shipper bị khách hành hung sau yêu cầu thử hàng | Nam shipper bị khách hành hung yêu cầu thử hàng |
| 65 | 0.231 | no | off | fr | RFI | Est de la RDC: le gouverneur intérimaire du Sud-Kivu décrète la suspension du trafic entre | Sud-Kivu RDC trafic suspension Bukavu Uvira |
