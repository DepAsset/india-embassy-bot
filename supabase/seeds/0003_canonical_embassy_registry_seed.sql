-- RAJDOOT canonical embassy registry seed generated from 123.xlsx.
-- This file applies the decisions confirmed in chat. Run after migration 0003.

begin;

-- Canonical active embassy registry.

insert into embassies (country_key, country_id, country_name, channel_id, channel_name, category_id, status, display_order) values
('afghanistan', null, 'Afghanistan', 1428503770492305508, 'afghanistan', 1371015715662069821, 'active', 0),
('algeria', null, 'Algeria', 1507296721003221123, 'algeria', 1470403546665975900, 'active', 1),
('argentina', null, 'Argentina', 1486413479534661672, 'argentina', 1470403546665975900, 'active', 2),
('australia', null, 'Australia', 1372102117686247424, 'australia', 1371015715662069821, 'active', 3),
('austria', null, 'Austria', 1430050640272425024, 'austria', 1371015715662069821, 'active', 4),
('bahrain', null, 'Bahrain', 1479154781959491717, 'bahrain', 1470403546665975900, 'active', 5),
('bangladesh', null, 'Bangladesh', 1500864361059582105, 'bangladesh', 1470403546665975900, 'active', 6),
('belgium', null, 'Belgium', 1455081974585884683, 'belgium', 1371015715662069821, 'active', 7),
('benin', null, 'Benin', 1495406928212263032, 'benin', 1470403546665975900, 'active', 8),
('bhutan-2', null, 'Bhutan 2', 1503714217306492928, 'bhutan-2', 1470403546665975900, 'active', 9),
('brazil', null, 'Brazil', 1476086944223068210, 'brazil', 1470403546665975900, 'active', 10),
('brunei', null, 'Brunei', 1515039528639922326, 'brunei', 1470403546665975900, 'active', 11),
('bulgaria', null, 'Bulgaria', 1470024855050125353, 'bulgaria', 1371015715662069821, 'active', 12),
('burundi', null, 'Burundi', 1493933378637004840, 'burundi', 1470403546665975900, 'active', 13),
('cambodia', null, 'Cambodia', 1429491483446214768, 'cambodia', 1371015715662069821, 'active', 14),
('canada', null, 'Canada', 1489632450454753513, 'canada', 1470403546665975900, 'active', 15),
('chile', null, 'Chile', 1461141059169026263, 'chile', 1371015715662069821, 'active', 16),
('china', null, 'China', 1522091155494408212, 'china', 1470403546665975900, 'active', 17),
('colombia', null, 'Colombia', 1491104370463342722, 'colombia', 1470403546665975900, 'active', 18),
('comoros', null, 'Comoros', 1480754731940057109, 'comoros', 1470403546665975900, 'active', 19),
('croatia', null, 'Croatia', 1493914607839088730, 'croatia', 1470403546665975900, 'active', 20),
('cyprus', null, 'Cyprus', 1371070839830741012, 'cyprus', 1371015715662069821, 'active', 21),
('denmark', null, 'Denmark', 1459255172432920780, 'denmark', 1371015715662069821, 'active', 22),
('egypt', null, 'Egypt', 1454758069908017185, 'egypt', 1371015715662069821, 'active', 23),
('el-salvador', null, 'El Salvador', 1493915173902094488, 'el-salvador', 1470403546665975900, 'active', 24),
('equatorial-guinea', null, 'Equatorial Guinea', 1482344436468809893, 'equatorial-guinea', 1470403546665975900, 'active', 25),
('eritrea', null, 'Eritrea', 1489916443431796817, 'eritrea', 1470403546665975900, 'active', 26),
('ethiopia', null, 'Ethiopia', 1470138775538503741, 'ethiopia', 1470403546665975900, 'active', 27),
('finland', null, 'Finland', 1486050633684615228, 'finland', 1470403546665975900, 'active', 28),
('france', null, 'France', 1463211725653545253, 'france', 1371015715662069821, 'active', 29),
('germany', null, 'Germany', 1424157854817980457, 'germany', 1371015715662069821, 'active', 30),
('greece', null, 'Greece', 1460286683537866883, 'greece', 1371015715662069821, 'active', 31),
('hungary', null, 'Hungary', 1529879133289709740, 'hungary', 1470403546665975900, 'active', 32),
('indonesia', null, 'Indonesia', 1379181830946951349, 'indonesia', 1371015715662069821, 'active', 33),
('iran', null, 'Iran', 1501547820665278605, 'iran', 1470403546665975900, 'active', 34),
('iraq', null, 'Iraq', 1470401290004856955, 'iraq', 1371015715662069821, 'active', 35),
('ireland', null, 'Ireland', 1524859134481141831, 'ireland', 1470403546665975900, 'active', 36),
('israel', null, 'Israel', 1524623948262936736, 'israel', 1470403546665975900, 'active', 37),
('italy', null, 'Italy', 1447166219290415234, 'italy', 1371015715662069821, 'active', 38),
('kazakhstan', null, 'Kazakhstan', 1463508367543898112, 'kazakhstan', 1371015715662069821, 'active', 39),
('kenya', null, 'Kenya', 1448407443129368606, 'kenya', 1371015715662069821, 'active', 40),
('kuwait', null, 'Kuwait', 1468153819740241971, 'kuwait', 1371015715662069821, 'active', 41),
('libya', null, 'Libya', 1526870480596766750, 'libya', 1470403546665975900, 'active', 42),
('lithuania', null, 'Lithuania', 1385535847612416040, 'lithuania', 1371015715662069821, 'active', 43),
('malaysia', null, 'Malaysia', 1430551073088737364, 'malaysia', 1371015715662069821, 'active', 44),
('mali', null, 'Mali', 1448569165492523110, 'mali', 1371015715662069821, 'active', 45),
('malta', null, 'Malta', 1481614869902917704, 'malta', 1470403546665975900, 'active', 46),
('mauritania', null, 'Mauritania', 1472955690976018574, 'mauritania', 1470403546665975900, 'active', 47),
('mexico', null, 'Mexico', 1486067321771655370, 'mexico', 1470403546665975900, 'active', 48),
('moldova', null, 'Moldova', 1479240649298415776, 'moldova', 1470403546665975900, 'active', 49),
('mongolia', null, 'Mongolia', 1531667374137278584, 'mongolia', 1470403546665975900, 'active', 50),
('morocco', null, 'Morocco', 1504711690321924156, 'morocco', 1470403546665975900, 'active', 51),
('myanmar', null, 'Myanmar', 1527856872672067664, 'myanmar', 1470403546665975900, 'active', 52),
('nepal', null, 'Nepal', 1460283405840285787, 'nepal', 1371015715662069821, 'active', 53),
('netherlands', null, 'Netherlands', 1470029200181166180, 'netherlands', 1371015715662069821, 'active', 54),
('new-zealand', null, 'New Zealand', 1484517424685646004, 'new-zealand', 1470403546665975900, 'active', 55),
('nigeria', null, 'Nigeria', 1525762915221635072, 'nigeria', 1470403546665975900, 'active', 56),
('pakistan', null, 'Pakistan', 1381447278639845466, 'pakistan', 1371015715662069821, 'active', 57),
('palestine', null, 'Palestine', 1439638466001633384, 'palestine', 1371015715662069821, 'active', 58),
('peru', null, 'Peru', 1385324800532287673, 'peru', 1371015715662069821, 'active', 59),
('philippines', null, 'Philippines', 1470632374675963924, 'philippines', 1470403546665975900, 'active', 60),
('poland', null, 'Poland', 1371025883548352512, 'poland', 1371015715662069821, 'active', 61),
('portugal', null, 'Portugal', 1455863199462064221, 'portugal', 1371015715662069821, 'active', 62),
('romania', null, 'Romania', 1456275889171071028, 'romania', 1371015715662069821, 'active', 63),
('russia', null, 'Russia', 1468188704970506367, 'russia', 1371015715662069821, 'active', 64),
('serbia', null, 'Serbia', 1429879873018658816, 'serbia', 1371015715662069821, 'active', 65),
('singapore', null, 'Singapore', 1446855261691187271, 'singapore', 1371015715662069821, 'active', 66),
('south-africa', null, 'South Africa', 1372101722591334450, 'south-africa', 1371015715662069821, 'active', 67),
('sri-lanka', null, 'Sri Lanka', 1431122263650074705, 'sri-lanka', 1371015715662069821, 'active', 68),
('sweden', null, 'Sweden', 1478689020711141386, 'sweden', 1470403546665975900, 'active', 69),
('syria', null, 'Syria', 1491664046699712592, 'syria', 1470403546665975900, 'active', 70),
'taiwan'
, null, 'Taiwan', 1428772736670503083, 'taiwan', 1371015715662069821, 'active', 71),
('tajikistan', null, 'Tajikistan', 1493915636777226320, 'tajikistan', 1470403546665975900, 'active', 72),
('tanzania', null, 'Tanzania', 1480894305139953816, 'tanzania', 1470403546665975900, 'active', 73),
('thailand', null, 'Thailand', 1438186017851965604, 'thailand', 1371015715662069821, 'active', 74),
('timor', null, 'Timor', 1371027318331670609, 'timor', 1371015715662069821, 'active', 75),
('togo', null, 'Togo', 1490922810392969226, 'togo', 1470403546665975900, 'active', 76),
('turkiye', null, 'Turkiye', 1439719666321719437, 'turkiye', 1371015715662069821, 'active', 77),
('turkmenistan', null, 'Turkmenistan', 1429491181724766308, 'turkmenistan', 1371015715662069821, 'active', 78),
('uae', null, 'UAE', 1467937579403051324, 'uae', 1371015715662069821, 'active', 79),
('uganda', null, 'Uganda', 1509181831726104726, 'uganda', 1470403546665975900, 'active', 80),
('ukraine', null, 'Ukraine', 1435938014454753513, 'ukraine', 1371015715662069821, 'active', 81),
('united-kingdom', null, 'United Kingdom', 1446961618889212034, 'united-kingdom', 1371015715662069821, 'active', 82),
('united-korea', null, 'United Korea', 1463211868599353435, 'united-korea', 1371015715662069821, 'active', 83),
('uruguay', null, 'Uruguay', 1371027857786142720, 'uruguay', 1371015715662069821, 'active', 84),
('usa', null, 'USA', 1438215365799710851, 'usa', 1371015715662069821, 'active', 85),
('uzbekistan', null, 'Uzbekistan', 1383143512517644338, 'uzbekistan', 1371015715662069821, 'active', 86),
('venezuela', null, 'Venezuela', 1471172188135755983, 'venezuela', 1470403546665975900, 'active', 87),
('vietnam', null, 'Vietnam', 1509391831726102748, 'vietnam', 1470403546665975900, 'active', 88),
('yemen', null, 'Yemen', 1493934097062694932, 'yemen', 1470403546665975900, 'active', 89)
on conflict (country_key) do update set country_name=excluded.country_name, channel_id=excluded.channel_id, channel_name=excluded.channel_name, category_id=excluded.category_id, status=excluded.status, display_order=excluded.display_order, updated_at=now();

-- The remaining canonical archive records are inserted separately so they never enter active ordering.

insert into embassies (country_key, country_id, country_name, channel_id, channel_name, category_id, status, archive_reason)
values
('bhutan-2-graveyard-1443223478223503421', null, 'Bhutan 2', 1443223478223503421, 'bhutan-2-deprecated', 1371015715662069821, 'archived', 'Archived legacy Bhutan channel; BHUTAN 2 is the active embassy.'),
('embassy-graveyard-1501896653651836958', null, 'Embassy', 1501896653651836958, 'embassy', 1470403546665975900, 'archived', 'Unmatched legacy channel moved to Embassy Graveyard.'),
('ireland-graveyard-1486124003667087551', null, 'Ireland', 1486124003667087551, 'irish', 1470403546665975900, 'archived', 'Consolidated into Ireland Embassy; legacy channel moved to Embassy Graveyard.'),
('kysely-graveyard-1479797519595733144', null, 'Kysely', 1479797519595733144, 'kysely', 1371015715662069821, 'archived', 'Unmatched legacy channel moved to Embassy Graveyard.'),
('yemen-graveyard-1527935424847151194', null, 'Yemen', 1527935424847151194, 'new-yemen', 1470403546665975900, 'archived', 'Unmatched legacy channel moved to Embassy Graveyard.')
on conflict (country_key) do update set status='archived', archive_reason=excluded.archive_reason, updated_at=now();

-- Legacy role reconciliation. All 98 roles are preserved in the mapping table first.
-- Six orphan roles are marked for deletion only after member/access safety verification.

insert into embassy_legacy_roles (embassy_id, role_id, role_name, disposition, notes)
select e.id, v.role_id, v.role_name, v.disposition, v.notes
from (values
(1371025675363942421, '🇵🇱Poland Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1371026711659151432, '🇯🇵 Japanese Embassy Access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1371027100072411167, '🇹🇱Timor Embassy  Access', 'mapped', 'Legacy role retained for migration verification.'),
(1371027779822424104, '🇺🇾Uruguay Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1371070716610351186, '🇨🇾Cyprus Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1372102290772725780, '🇿🇦South Africa Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1372102415087702058, '🇦🇺Australia Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1379181989931782215, '🇮🇩Indonesia Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1381489845112803338, '🇵🇰Pakistani Embassy Access', 'mapped', 'Mapped to Pakistan after spelling correction.'),
(1383143132308176906, '🇺🇿Uzbekistan Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1385324903217238067, '🇵🇪Peru Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1385535923911000095, '🇱🇹Lithuania  Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1424157929124270172, '🇩🇪Germany Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1428504069127016539, '🇦🇫Afganistan Embassy Access', 'mapped', 'Mapped to Afghanistan after spelling correction.'),
(1428772901544530062, '🇹🇼Taiwan  Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1429491684009316483, '🇹🇲Turkmenistan Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1429491743572623440, '🇰🇭Combodia Embassy Access', 'mapped', 'Mapped to Cambodia after spelling correction.'),
(1429880301055901828, '🇷🇸Serbia Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1430050814650744853, '🇦🇹Austria Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1430551202621423737, '🇲🇾Malaysia Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1431122490125586542, '🇱🇰Sri Lanka Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1435938370655354932, '🇺🇦Ukraine Embassy Access', 'mapped', 'Duplicate legacy Ukraine role. Preserve during migration verification.'),
(1438186143257464872, '🇹🇭Thailand Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1438215643290796063, '🇺🇸USA Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1439597637253730416, '🇵🇸Palestine  Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1439719955762385136, '🇹🇷Turkiye Embassy Access', 'mapped', 'Mapped to Turkiye after spelling correction.'),
(1443223354856177845, '🇧🇹Bhutan Embassy Access', 'mapped', 'Mapped to active BHUTAN 2 embassy.'),
(1446856209142517861, '🇸🇬Singapore Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1446961693300363456, '🇬🇧United Kingdom Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1447166281886339273, '🇮🇹Italy Embassy', 'mapped', 'Legacy role retained for migration verification.'),
(1448407544904159436, '🇰🇪Kenya Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1448569780691927111, '🇲🇱Mali Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1454758305938411604, '🇪🇬Egypt Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1455082027769528433, '🇧🇪Belgium Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1455863436989956126, '🇵🇹Portugal Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1456275990203334873, '🇷🇴Romania Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1459255313357082866, '🇩🇰Denmark Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1460283462182371338, '🇳🇵Nepal Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1460286900647759994, '🇬🇷Greece Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1461140988239282287, '🇨🇱Chile Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1463212141275254976, '🇫🇷France Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1463212219981631544, '🇰🇵United Korea Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1463508063032971408, '🇰🇿Kazakhstan Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1467939362372190315, '🇦🇪UAE embassy access', 'mapped', 'Legacy role retained for migration verification.'),
(1468155006237671556, 'Kuwait-Embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1468190237300756686, 'Russia-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1470025022213980245, 'Bulgaria-Embassy-Access', 'mapped', 'Legacy role retained for migration verification.'),
(1470029326958329856, 'netherland-embassy-access', 'mapped', 'Mapped to Netherlands after spelling correction.'),
(1470138834317479977, '🇪🇹Ethiopia Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1470401377032339630, 'Iraq Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1470632431135494418, '🇵🇭Philippines Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1471173102711869460, '🇻🇪Venezuela Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1472956688062480424, 'Mauritania-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1474464243465060587, 'Benin Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1476088988422111447, 'brazil-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1478689178299404368, 'sweden embassy access', 'mapped', 'Legacy role retained for migration verification.'),
(1479155293785952447, 'Bahrain-Embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1479241539690561618, 'Moldova Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1480093927682998312, 'saudi-embassy-access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1480755024421326890, 'Comoros-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1480894409879978105, '🇹🇿Tanznia Embassy Access', 'mapped', 'Mapped to Tanzania after spelling correction.'),
(1480994278049058846, 'lebanon-embassy-access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1481333990878085352, 'ukraine-embassy-access', 'mapped', 'Duplicate legacy Ukraine role. Preserve during migration verification.'),
(1481614966132838533, 'malta-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1482344534175252654, 'equatorial-guinea-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1484517499201654895, 'New Zealand Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1486050704576614430, 'Finland Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1486066865381052569, 'Mexico Embassy Access', 'mapped', 'Legacy role retained for migration verification.'),
(1486414227056103544, 'Argentina -embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1489632556478501015, 'Canada-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1489916693886140436, 'eritrea-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1490923628072534016, 'Togo-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1491104477510631737, 'colombia-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1491663677160689704, 'Syria-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1491899325112914001, 'Ireland Embassy Access', 'mapped', 'Consolidated into the active Ireland Embassy. Keep during migration verification.'),
(1492231320724705281, 'yemen-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1492862712387080364, 'Burundi-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1493691590579851424, 'el salvador embassy', 'mapped', 'Legacy role retained for migration verification.'),
(1493693272848339075, 'Tajikistan-embassy', 'mapped', 'Legacy role retained for migration verification.'),
(1493914746632667197, 'Croatia-embassy', 'mapped', 'Legacy role retained for migration verification.'),
(1500864564781383881, 'Bangladesh-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1501547962126307388, 'iran-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1501850754301034507, 'Andorra-embassy-access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1504413880514777098, 'Congo-embassy-access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1504525278355918960, 'cameroon-embassy-access', 'orphan_pending_deletion', 'No embassy exists for this role. Delete only after safety verification.'),
(1504711433089187911, 'Morocco-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1507296817614950430, 'Algeria-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1509181925686906880, 'uganda-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1509392303817494732, 'Vietnam-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1515039580787576884, 'Brunei-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1522091363590475918, 'China-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1524624042327468468, 'Israel-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1524858601783427182, 'Ireland-embassy-access', 'mapped', 'Consolidated into the active Ireland Embassy. Keep during migration verification.'),
(1525762748837789696, 'Nigeria-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1526870245090787328, 'Libya-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1527857188050174033, 'Myanmar-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1529879347673174197, 'Hungary-embassy-access', 'mapped', 'Legacy role retained for migration verification.'),
(1531667433671098488, 'mongolia-embassy-access', 'mapped', 'Legacy role retained for migration verification.')
) as v(role_id, role_name, disposition, notes)
left join embassies e on e.channel_id in (
    select case
        when v.role_id = 1443223354856177845 then 1503714217306492928
        when v.role_id = 1428504069127016539 then 1428503770492305508
        when v.role_id = 1429491743572623440 then 1429491483446214768
        when v.role_id = 1381489845112803338 then 1381447278639845466
        when v.role_id = 1439719955762385136 then 1439719666321719437
        when v.role_id = 1470029326958329856 then 1470029200181166180
        when v.role_id = 1480894409879978105 then 1480894305139953816
        when v.role_id in (1491899325112914001, 1524858601783427182) then 1524859134481141831
        else null
    end
) and e.status='active'
on conflict (role_id) do update set embassy_id=excluded.embassy_id, role_name=excluded.role_name, disposition=excluded.disposition, notes=excluded.notes, updated_at=now();

update embassies e
set legacy_access_role_id = r.role_id,
    updated_at = now()
from (
    select embassy_id, min(role_id) role_id
    from embassy_legacy_roles
    where embassy_id is not null and disposition='mapped'
    group by embassy_id
) r
where e.id=r.embassy_id;

update embassies set display_order=null, updated_at=now() where status='archived';

commit;
