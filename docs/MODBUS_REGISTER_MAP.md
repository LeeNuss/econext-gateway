# Grant Aerona R290 (Axen) heat pump Modbus register map

Registers of the outdoor unit as seen on the RS-485 link between the Aerona Smart Controller wiring centre and the outdoor unit. Read from the live bus, matched against the controller's own parameter table, and for the parts the wiring centre never polls, found by scanning with a second master. The Chofu / Aerona3 documentation does not apply: that unit uses a different layout (holding 0 to 102).

## Link

- Modbus RTU, 9600 baud, 8N2. The outdoor unit is slave 251; the wiring centre is the only master.
- One poll cycle every 10.8 s: 168 registers in 24 exchanges. Request to reply takes 47 ms, followed by 330 to 356 ms of silence before the next request.
- A second master can transmit in that silence. The unit answers it normally and the wiring centre's polling is not disturbed.
- Function codes 01 and 02 (coils, discrete inputs) are rejected as illegal function. The unit has only input and holding registers.
- The wiring centre's frames sometimes arrive with garbage lead bytes and truncated tails, in bursts of 5 to 12 minutes a few times a day, also with the heat pump idle and no other master on the bus. The wiring centre retries with the start address shifted by one and carries on.

## What the wiring centre does

- Polls input 0 to 103, 121 and 1201 to 1238, and holding 2100 to 2114, 2150, 2155, 2200, 6050, 6061, 6231 to 6233, 6244, 6271 and 6273. Holding 2200 is rejected with exception 02 every time.
- Writes only three registers, all with function 06: 2101 (run request), 2107 (target outgoing temperature x10) and occasionally 2103 (bitfield). A start is `2101 = 1` followed by `2107 = <target>`; a stop is `2101 = 0`.
- Never sends a compressor frequency. Silent mode levels are frequency caps held in the service block (6017, 6047).
- A run starts only once the target is more than 5 K above the outgoing water temperature (input 43), about 25 s after that.

## Controller mirror

The controller keeps every polled register as a parameter named `AXEN_REGISTER_<n>` (32-bit pairs as `<n>_<n+1>`), next to decoded parameters such as `AxenOutgoingTemp` and `HPStatusComprHz`. So the raw link can also be read through the gateway API, about ten seconds late. The values match the bus except register 61, which the controller stores divided by 10; register 64 has the same float type and is probably scaled the same way.

The controller also carries `AXEN_REGISTER_2000..2016_RW_R32`, a write block for the Aerona3 R32 variant. It does not exist on this unit.

## Block layout

| Block | Type | Registers | Polled by the wiring centre | Contents |
|---|---|---|---|---|
| 0 to 131 | input | 132 | 0 to 103, 121 | live values: temperatures, pressures, fan and compressor, states; 104 to 120 read zero |
| 1200 to 1238 | input | 39 | 1201 to 1238 | 32-bit counters and energies, live power figures while running |
| 3000 to 3274 | input | 275 | none | same offsets as the service block, all zero |
| 4000 to 4274 | input | 275 | none | maximum of each service parameter at 6000 + offset |
| 5000 to 5274 | input | 275 | none | minimum of each service parameter at 6000 + offset |
| 2100 to 2114 | holding | 15 | all | command block: run request, target temperature, bitfield, set points |
| 2150 to 2155 | holding | 6 | 2150, 2155 | reboot, pump manual preset; 2151 to 2154 read zero |
| 2200 | holding | 0 | polled | always rejected with exception 02 |
| 6000 to 6274 | holding | 275 | 6050, 6061, 6231 to 6233, 6244, 6271, 6273 | service parameters, writable with function 06 within the limits at 5000 / 4000 |

Nothing else answers in either 16-bit space at a stride of 16, nor at a stride of 8 over 2300 to 2999 and 6275 to 8191.

## Service parameters (holding 6000 to 6274)

- For every offset i in 0 to 274, input 4000 + i >= holding 6000 + i >= input 5000 + i: the input tables at 4000 and 5000 are the maximum and minimum of each service parameter.
- Writes with function 06 take effect during a run (shown for 6046 and 6047).
- The unit puts the service parameters back to factory values after a power cycle or factory reset.
- Compressor frequency: 6046 is the minimum (factory 15 Hz, limits 10 to 100), 6047 the silent mode level_2 cap (factory 40 Hz), 6017 most likely the level_1 cap (factory 50 Hz). The frequency itself is input 78; 6041 is not the minimum.
- Fan: 6053 is the fan speed maximum (factory 850 rpm, limits 300 to 1000). After every compressor start the fan runs a burst up to this maximum, independent of the fan table the wiring centre polls (6231 to 6233, 6244, at most 650). The whole fan group 6049 to 6054 and 6231 to 6245 has limits of 200 or 300 to 1000, an rpm range. 6234 to 6236 (500 / 550 / 600) look like a second three-step fan table.
- 6013 = 480 equals the expansion valve's idle position in input 70.
- 6129 to 6149 and 6156 to 6176 are two 21-entry tables that look like values by temperature step.

## Register table

Value is a reading with the heat pump idle and the service parameters at factory values. Signed shows the 16-bit two's complement where it differs. Min and Max are the unit's own limits from the input tables at 5000 and 4000, for the 6000 block only. Controller parameter is the gateway index and name that carries the same register. A meaning starting with "probably" comes from behaviour or magnitude rather than a decode or a write test; an empty meaning is not known.

| Type | Addr | Value | Signed | Min | Max | Controller parameter | Meaning |
|---|---|---|---|---|---|---|---|
| input | 0 | 132 |  |  |  | 1147 AXEN_REGISTER_00 | constant 132, purpose unknown |
| input | 1 | 0 |  |  |  | 1148 AXEN_REGISTER_01 |  |
| input | 2 | 0 |  |  |  | 1149 AXEN_REGISTER_02 |  |
| input | 3 | 0 |  |  |  | 1150 AXEN_REGISTER_03 |  |
| input | 4 | 0 |  |  |  | 1151 AXEN_REGISTER_04 |  |
| input | 5 | 0 |  |  |  | 1152 AXEN_REGISTER_05 |  |
| input | 6 | 0 |  |  |  | 1153 AXEN_REGISTER_06 |  |
| input | 7 | 1 |  |  |  | 1154 AXEN_REGISTER_07 | constant 1 |
| input | 8 | 3 |  |  |  | 1155 AXEN_REGISTER_08 | constant 3 |
| input | 9 | 4355 |  |  |  | 1156 AXEN_REGISTER_09 | constant 4355 = 0x1103, probably a model or version code (also in the R32 block at 2008) |
| input | 10 | 25 |  |  |  | 1157 AXEN_REGISTER_10 | setpoint echo block 10 to 29; 10 = HPStatusPresetTemp |
| input | 11 | 5 |  |  |  | 1158 AXEN_REGISTER_11 |  |
| input | 12 | 75 |  |  |  | 1159 AXEN_REGISTER_12 |  |
| input | 13 | 18 |  |  |  | 1160 AXEN_REGISTER_13 |  |
| input | 14 | 70 |  |  |  | 1161 AXEN_REGISTER_14 |  |
| input | 15 | 20 |  |  |  | 1162 AXEN_REGISTER_15 |  |
| input | 16 | 25 |  |  |  | 1163 AXEN_REGISTER_16 |  |
| input | 17 | 5 |  |  |  | 1164 AXEN_REGISTER_17 |  |
| input | 18 | 75 |  |  |  | 1165 AXEN_REGISTER_18 |  |
| input | 19 | 18 |  |  |  | 1166 AXEN_REGISTER_19 |  |
| input | 20 | 25 |  |  |  | 1167 AXEN_REGISTER_20 |  |
| input | 21 | 5 |  |  |  | 1168 AXEN_REGISTER_21 |  |
| input | 22 | 55 |  |  |  | 1169 AXEN_REGISTER_22 |  |
| input | 23 | 18 |  |  |  | 1170 AXEN_REGISTER_23 |  |
| input | 24 | 0 |  |  |  | 1171 AXEN_REGISTER_24 |  |
| input | 25 | 0 |  |  |  | 1172 AXEN_REGISTER_25 |  |
| input | 26 | 25 |  |  |  | 1173 AXEN_REGISTER_26 |  |
| input | 27 | 5 |  |  |  | 1174 AXEN_REGISTER_27 |  |
| input | 28 | 55 |  |  |  | 1175 AXEN_REGISTER_28 |  |
| input | 29 | 18 |  |  |  | 1176 AXEN_REGISTER_29 |  |
| input | 30 | 300 |  |  |  | 1177 AXEN_REGISTER_30 | constant |
| input | 31 | 170 |  |  |  | 1178 AXEN_REGISTER_31 |  |
| input | 32 | 0 |  |  |  | 1179 AXEN_REGISTER_32 |  |
| input | 33 | 0 |  |  |  | 1180 AXEN_REGISTER_33 |  |
| input | 34 | 0 |  |  |  | 1181 AXEN_REGISTER_34 |  |
| input | 35 | 1 |  |  |  | 1182 AXEN_REGISTER_35 |  |
| input | 36 | 0 |  |  |  | 1183 AXEN_REGISTER_36 |  |
| input | 37 | 2 |  |  |  | 1184 AXEN_REGISTER_37 |  |
| input | 38 | 0 |  |  |  | 1185 AXEN_REGISTER_38 |  |
| input | 39 | 0 |  |  |  | 1186 AXEN_REGISTER_39 |  |
| input | 40 | 0 |  |  |  | 1187 AXEN_REGISTER_40 |  |
| input | 41 | 65036 | -500 |  |  | 1188 AXEN_REGISTER_41 | -50.0 = sensor not fitted (AxenBufferTemp) |
| input | 42 | 163 |  |  |  | 1189 AXEN_REGISTER_42 | return water temperature x10 (AxenReturnTemp, panel TempReturn) |
| input | 43 | 165 |  |  |  | 1190 AXEN_REGISTER_43 | outgoing water temperature x10 (AxenOutgoingTemp, panel TempOutlet) |
| input | 44 | 65036 | -500 |  |  | 1191 AXEN_REGISTER_44 | -50.0 = sensor not fitted |
| input | 45 | 65036 | -500 |  |  | 1192 AXEN_REGISTER_45 | -50.0 = sensor not fitted |
| input | 46 | 65236 | -300 |  |  | 1193 AXEN_REGISTER_46 | DHW tank temperature x10, -30.0 here = not fitted (AxenDHWTemp) |
| input | 47 | 65036 | -500 |  |  | 1194 AXEN_REGISTER_47 | -50.0 = sensor not fitted |
| input | 48 | 65236 | -300 |  |  | 1195 AXEN_REGISTER_48 | probably a copy of 46 |
| input | 49 | 173 |  |  |  | 1196 AXEN_REGISTER_49 | temperature x10, falls to about 4 C while running: probably the evaporator coil |
| input | 50 | 189 |  |  |  | 1197 AXEN_REGISTER_50 | outdoor air temperature x10 (AxenOutdoorTemp) |
| input | 51 | 171 |  |  |  | 1198 AXEN_REGISTER_51 | temperature x10, rises to about 23 C while running: probably the condenser / plate heat exchanger |
| input | 52 | 178 |  |  |  | 1199 AXEN_REGISTER_52 | discharge temperature x10 (AxenDischargeTemp) |
| input | 53 | 182 |  |  |  | 1200 AXEN_REGISTER_53 | suction temperature x10 (AxenSuctionTemp) |
| input | 54 | 0 |  |  |  | 1201 AXEN_REGISTER_54 |  |
| input | 55 | 0 |  |  |  | 1202 AXEN_REGISTER_55 |  |
| input | 56 | 165 |  |  |  | 1203 AXEN_REGISTER_56 | copy of 43, outgoing water temperature x10 |
| input | 57 | 65036 | -500 |  |  | 1204 AXEN_REGISTER_57 | -50.0 = sensor not fitted |
| input | 58 | 0 |  |  |  | 1205 AXEN_REGISTER_58 |  |
| input | 59 | 0 |  |  |  | 1206 AXEN_REGISTER_59 |  |
| input | 60 | 0 |  |  |  | 1207 AXEN_REGISTER_60 |  |
| input | 61 | 2.0 |  |  |  | 1208 AXEN_REGISTER_61 | the controller stores it divided by 10; 0 to 24 seen |
| input | 62 | 0 |  |  |  | 1209 AXEN_REGISTER_62 | water pump speed %, 0/15/60 steps (HA pump_speed) |
| input | 63 | 0 |  |  |  | 1210 AXEN_REGISTER_63 | 0 to 15 while running |
| input | 64 | 0.0 |  |  |  | 1211 AXEN_REGISTER_64 | the controller stores it divided by 10 (probably); 0 to 9 seen |
| input | 65 | 0 |  |  |  | 1212 AXEN_REGISTER_65 |  |
| input | 66 | 140 |  |  |  | 1213 AXEN_REGISTER_66 | constant (140 to 190 seen) |
| input | 67 | 400 |  |  |  | 1214 AXEN_REGISTER_67 | constant (400 to 410 seen) |
| input | 68 | 140 |  |  |  | 1215 AXEN_REGISTER_68 | constant (140 to 190 seen) |
| input | 69 | 290 |  |  |  | 1216 AXEN_REGISTER_69 | constant (290 to 300 seen) |
| input | 70 | 480 |  |  |  | 1217 AXEN_REGISTER_70 | probably the expansion valve position: 480 idle, 120 to 250 running; holding 6013 = 480 |
| input | 71 | 10 |  |  |  | 1218 AXEN_REGISTER_71 | constant 10 |
| input | 72 | 0 |  |  |  | 1219 AXEN_REGISTER_72 | fan speed rpm (AxenFanSpeed / HPStatusFanRPM); the start-up burst peaks just under holding 6053 |
| input | 73 | 0 |  |  |  | 1220 AXEN_REGISTER_73 |  |
| input | 74 | 234 |  |  |  | 1221 AXEN_REGISTER_74 | probably mains voltage, V (232 to 236) |
| input | 75 | 0 |  |  |  | 1222 AXEN_REGISTER_75 | 0 idle, 7 to 48 running; moves with load but is not the frequency |
| input | 76 | 327 |  |  |  | 1223 AXEN_REGISTER_76 | probably DC bus voltage, V (324 idle, up to 363 running) |
| input | 77 | 0 |  |  |  | 1224 AXEN_REGISTER_77 | 0 idle, 25 to 43 running |
| input | 78 | 0 |  |  |  | 1225 AXEN_REGISTER_78 | compressor frequency Hz (AxenCompressorFreq / HPStatusComprHz): 3 Hz steps above the minimum (6046), held at the silent mode cap (6017 / 6047) |
| input | 79 | 0 |  |  |  | 1226 AXEN_REGISTER_79 | tracks 78, differs at starts (7 while 78 is already 39): probably the target frequency |
| input | 80 | 0 |  |  |  | 1227 AXEN_REGISTER_80 | flag 0/1 |
| input | 81 | 0 |  |  |  | 1228 AXEN_REGISTER_81 | flag 0/1 |
| input | 82 | 0 |  |  |  | 1229 AXEN_REGISTER_82 | state 0/2/7 |
| input | 83 | 0 |  |  |  | 1230 AXEN_REGISTER_83 | state 0/8 |
| input | 84 | 0 |  |  |  | 1231 AXEN_REGISTER_84 |  |
| input | 85 | 0 |  |  |  | 1232 AXEN_REGISTER_85 |  |
| input | 86 | 688 |  |  |  | 1233 AXEN_REGISTER_86 | probably high side pressure x100 bar: 5.4 idle, 8.5 to 12.5 running; equal to 87 when off |
| input | 87 | 685 |  |  |  | 1234 AXEN_REGISTER_87 | probably low side pressure x100 bar: 5.4 idle, 3.7 to 4.5 running |
| input | 88 | 0 |  |  |  | 1235 AXEN_REGISTER_88 |  |
| input | 89 | 0 |  |  |  | 1236 AXEN_REGISTER_89 |  |
| input | 90 | 0 |  |  |  | 1237 AXEN_REGISTER_90 |  |
| input | 91 | 0 |  |  |  | 1238 AXEN_REGISTER_91 |  |
| input | 92 | 0 |  |  |  | 1239 AXEN_REGISTER_92 |  |
| input | 93 | 0 |  |  |  | 1240 AXEN_REGISTER_93 |  |
| input | 94 | 0 |  |  |  | 1241 AXEN_REGISTER_94 |  |
| input | 95 | 0 |  |  |  | 1242 AXEN_REGISTER_95 |  |
| input | 96 | 0 |  |  |  | 1243 AXEN_REGISTER_96 |  |
| input | 97 | 0 |  |  |  | 1244 AXEN_REGISTER_97 |  |
| input | 98 | 0 |  |  |  | 1245 AXEN_REGISTER_98 |  |
| input | 99 | 0 |  |  |  | 1246 AXEN_REGISTER_99 |  |
| input | 100 | 0 |  |  |  | 1247 AXEN_REGISTER_100 |  |
| input | 101 | 0 |  |  |  | 1248 AXEN_REGISTER_101 |  |
| input | 102 | 8192 |  |  |  | 1249 AXEN_REGISTER_102 | bitfield 8192/8194 (bit 13 always set, bit 1 while running) |
| input | 103 | 0 |  |  |  | 1250 AXEN_REGISTER_103 | probably work mode: 0 idle, 2 running |
| input | 104 | 0 |  |  |  | - | reads 0, not polled |
| input | 105 | 0 |  |  |  | - | reads 0, not polled |
| input | 106 | 0 |  |  |  | - | reads 0, not polled |
| input | 107 | 0 |  |  |  | - | reads 0, not polled |
| input | 108 | 0 |  |  |  | - | reads 0, not polled |
| input | 109 | 0 |  |  |  | - | reads 0, not polled |
| input | 110 | 0 |  |  |  | - | reads 0, not polled |
| input | 111 | 0 |  |  |  | - | reads 0, not polled |
| input | 112 | 0 |  |  |  | - | reads 0, not polled |
| input | 113 | 0 |  |  |  | - | reads 0, not polled |
| input | 114 | 0 |  |  |  | - | reads 0, not polled |
| input | 115 | 0 |  |  |  | - | reads 0, not polled |
| input | 116 | 0 |  |  |  | - | reads 0, not polled |
| input | 117 | 0 |  |  |  | - | reads 0, not polled |
| input | 118 | 0 |  |  |  | - | reads 0, not polled |
| input | 119 | 0 |  |  |  | - | reads 0, not polled |
| input | 120 | 0 |  |  |  | - | reads 0, not polled |
| input | 122 | 48 |  |  |  | - |  |
| input | 123 | 48 |  |  |  | - |  |
| input | 124 | 49 |  |  |  | - |  |
| input | 125 | 46 |  |  |  | - |  |
| input | 126 | 48 |  |  |  | - |  |
| input | 127 | 56 |  |  |  | - |  |
| input | 128 | 45 |  |  |  | - |  |
| input | 129 | 48 |  |  |  | - |  |
| input | 130 | 39 |  |  |  | - |  |
| input | 131 | 275 |  |  |  | - | probably the size of the parameter tables (275) |
| input | 121 | 86 |  |  |  | 1283 AXEN_REGISTER_121 | outdoor unit firmware version, gateway reports it as HP firmware 86 |
| input | 1200 | 39 |  |  |  | - |  |
| input | 1201 | 0 |  |  |  | 1284 AXEN_REGISTER_1201 | probably work mode: 0 idle, 2 running |
| input | 1202 | 91808 |  |  |  | 1285 AXEN_REGISTER_1202_1203 | electrical energy total, 32-bit with 1203, /100 kWh (HA energy_consumed_total) |
| input | 1203 | 91808 |  |  |  | 1285 AXEN_REGISTER_1202_1203 (low word) |  |
| input | 1204 | 2435 |  |  |  | 1286 AXEN_REGISTER_1204_1205 | electrical energy cooling, 32-bit with 1205, /100 kWh |
| input | 1205 | 2435 |  |  |  | 1286 AXEN_REGISTER_1204_1205 (low word) |  |
| input | 1206 | 76419 |  |  |  | 1287 AXEN_REGISTER_1206_1207 | electrical energy heating, 32-bit with 1207, /100 kWh |
| input | 1207 | 76419 |  |  |  | 1287 AXEN_REGISTER_1206_1207 (low word) |  |
| input | 1208 | 0 |  |  |  | 1288 AXEN_REGISTER_1208_1209 | electrical energy DHW, 32-bit with 1209, /100 kWh |
| input | 1209 | 0 |  |  |  | 1288 AXEN_REGISTER_1208_1209 (low word) |  |
| input | 1210 | 17950 |  |  |  | 1289 AXEN_REGISTER_1210_1211 | thermal energy cooling, 32-bit with 1211, /100 kWh (= panel CoolingPower_all) |
| input | 1211 | 17950 |  |  |  | 1289 AXEN_REGISTER_1210_1211 (low word) |  |
| input | 1212 | 396743 |  |  |  | 1290 AXEN_REGISTER_1212_1213 | thermal energy heating, 32-bit with 1213, /100 kWh (= panel HeatingPower_all) |
| input | 1213 | 396743 |  |  |  | 1290 AXEN_REGISTER_1212_1213 (low word) |  |
| input | 1214 | 0 |  |  |  | 1291 AXEN_REGISTER_1214_1215 | 32-bit with 1215, 0 |
| input | 1215 | 0 |  |  |  | 1291 AXEN_REGISTER_1214_1215 (low word) |  |
| input | 1216 | 4806 |  |  |  | 1292 AXEN_REGISTER_1216_1217 | 32-bit with 1217, 4806 |
| input | 1217 | 4806 |  |  |  | 1292 AXEN_REGISTER_1216_1217 (low word) |  |
| input | 1218 | 56732 |  |  |  | 1293 AXEN_REGISTER_1218_1219 | 32-bit with 1219, 56732 |
| input | 1219 | 56732 |  |  |  | 1293 AXEN_REGISTER_1218_1219 (low word) |  |
| input | 1220 | 0 |  |  |  | 1294 AXEN_REGISTER_1220_1221 | 32-bit with 1221, 0 |
| input | 1221 | 0 |  |  |  | 1294 AXEN_REGISTER_1220_1221 (low word) |  |
| input | 1222 | 0 |  |  |  | 1295 AXEN_REGISTER_1222 |  |
| input | 1223 | 0 |  |  |  | 1296 AXEN_REGISTER_1223 |  |
| input | 1224 | 234 |  |  |  | 1297 AXEN_REGISTER_1224 | copy of 74 |
| input | 1225 | 0 |  |  |  | 1298 AXEN_REGISTER_1225 |  |
| input | 1226 | 0 |  |  |  | 1299 AXEN_REGISTER_1226 |  |
| input | 1227 | 0 |  |  |  | 1300 AXEN_REGISTER_1227 |  |
| input | 1228 | 0 |  |  |  | 1301 AXEN_REGISTER_1228 |  |
| input | 1229 | 0 |  |  |  | 1302 AXEN_REGISTER_1229 |  |
| input | 1230 | 4 |  |  |  | 1303 AXEN_REGISTER_1230_1231 | 32-bit with 1231; 4 idle, 784 to 984 running |
| input | 1231 | 4 |  |  |  | 1303 AXEN_REGISTER_1230_1231 (low word) |  |
| input | 1232 | 0 |  |  |  | 1304 AXEN_REGISTER_1232_1233 |  |
| input | 1233 | 0 |  |  |  | 1304 AXEN_REGISTER_1232_1233 (low word) |  |
| input | 1234 | 0 |  |  |  | 1305 AXEN_REGISTER_1234_1235 | 32-bit with 1235; 0 idle, 1392 to 7053 running: probably thermal power W |
| input | 1235 | 0 |  |  |  | 1305 AXEN_REGISTER_1234_1235 (low word) |  |
| input | 1236 | 0 |  |  |  | 1306 AXEN_REGISTER_1236_1237 | 32-bit with 1237 |
| input | 1237 | 0 |  |  |  | 1306 AXEN_REGISTER_1236_1237 (low word) |  |
| input | 1238 | 0 |  |  |  | 1307 AXEN_REGISTER_1238 | 0 idle, 194 to 1286 running: probably electrical power W |
| input | 3000-3274 | all 0 |  |  |  | - | same 275 offsets as holding 6000 to 6274, all zero |
| input | 4000-4274 | see 6000 rows |  |  |  | - | maximum for each holding 6000+i parameter (holds for all 275) |
| input | 5000-5274 | see 6000 rows |  |  |  | - | minimum for each holding 6000+i parameter (holds for all 275) |
| holding | 2100 | 2 |  |  |  | 1268 AXEN_REGISTER_2100_RW | mode, panel range 0 to 2, always 2 |
| holding | 2101 | 0 |  |  |  | 1269 AXEN_REGISTER_2101_RW | run request written by the wiring centre: 0 off, 1 on (range 0 to 3) |
| holding | 2102 | 0 |  |  |  | 1270 AXEN_REGISTER_2102_RW | flag 0/1 |
| holding | 2103 | 0 |  |  |  | 1271 AXEN_REGISTER_2103_RW | bitfield: bit 0 manual defrost, bit 14 purge (HA switches); value 32 seen in Feb |
| holding | 2104 | 0 |  |  |  | 1272 AXEN_REGISTER_2104_RW | flag 0/1 |
| holding | 2105 | 450 |  |  |  | 1273 AXEN_REGISTER_2105_RW | 450 = 45.0, panel range 25 to 75 |
| holding | 2106 | 200 |  |  |  | 1274 AXEN_REGISTER_2106_RW | 200 = 20.0, panel range 5 to 25 |
| holding | 2107 | 560 |  |  |  | 1275 AXEN_REGISTER_2107_RW | target outgoing water temperature x10, written on every start; 25 to 34 heating, 50 to 56 DHW seen |
| holding | 2108 | 50 |  |  |  | 1276 AXEN_REGISTER_2108_RW | 50 = 5.0, panel range 5 to 25 |
| holding | 2109 | 270 |  |  |  | 1277 AXEN_REGISTER_2109_RW | 270 = 27.0, panel range 35 to 75 |
| holding | 2110 | 120 |  |  |  | 1278 AXEN_REGISTER_2110_RW | 120 = 12.0, panel range 5 to 25 |
| holding | 2111 | 350 |  |  |  | 1279 AXEN_REGISTER_2111_RW | 350 = 35.0, panel range 35 to 75 |
| holding | 2112 | 50 |  |  |  | 1280 AXEN_REGISTER_2112_RW | 50 = 5.0, panel range 5 to 25 |
| holding | 2113 | 270 |  |  |  | 1281 AXEN_REGISTER_2113_RW | 270 = 27.0, panel range 35 to 75 |
| holding | 2114 | 250 |  |  |  | 1282 AXEN_REGISTER_2114_RW | 250 = 25.0, panel range 10 to 35; possibly the minimum heating target (2107 is never below 25.0) |
| holding | 2150 | 0 |  |  |  | 1369 AXEN_REGISTER_2150_RW-reboot_unit | reboot outdoor unit (panel AXEN_REGISTER_2150_RW-reboot_unit) |
| holding | 2155 | 100 |  |  |  | 1370 AXEN_2155-uhsPumpManualPreset | water pump manual preset % (panel AXEN_2155-uhsPumpManualPreset) |
| holding | 2200 | 12288 |  |  |  | 1308 AXEN_REGISTER_2200_RW | polled every cycle, always rejected with exception 02 |
| holding | 6000 | 2 |  | 0 | 5 | - |  |
| holding | 6001 | 5 |  | 2 | 15 | - |  |
| holding | 6002 | 0 |  | -10 | 15 | - |  |
| holding | 6003 | 65535 | -1 | -5 | 10 | - |  |
| holding | 6004 | 68 |  | 10 | 120 | - |  |
| holding | 6005 | 68 |  | 10 | 120 | - |  |
| holding | 6006 | 68 |  | 10 | 120 | - |  |
| holding | 6007 | 400 |  | 0 | 480 | - |  |
| holding | 6008 | 400 |  | 0 | 480 | - |  |
| holding | 6009 | 400 |  | 0 | 480 | - |  |
| holding | 6010 | 65531 | -5 | -15 | 0 | - |  |
| holding | 6011 | 8 |  | 0 | 15 | - |  |
| holding | 6012 | 40 |  | 20 | 90 | - |  |
| holding | 6013 | 480 |  | 0 | 480 | - | probably EEV maximum steps (equals the idle position in input 70) |
| holding | 6014 | 65 |  | 30 | 120 | - |  |
| holding | 6015 | 105 |  | 15 | 120 | - |  |
| holding | 6016 | 1 |  | 0 | 1 | - |  |
| holding | 6017 | 50 |  | 30 | 120 | - | probably the silent mode level_1 compressor cap, Hz: level_1 runs plateau at 50, same limits as 6047 |
| holding | 6018 | 65 |  | 55 | 75 | - |  |
| holding | 6019 | 30 |  | 20 | 120 | - |  |
| holding | 6020 | 0 |  | 0 | 2 | - |  |
| holding | 6021 | 0 |  | 0 | 120 | - |  |
| holding | 6022 | 0 |  | 0 | 120 | - |  |
| holding | 6023 | 0 |  | 0 | 120 | - |  |
| holding | 6024 | 0 |  | 0 | 120 | - |  |
| holding | 6025 | 0 |  | 0 | 120 | - |  |
| holding | 6026 | 0 |  | 0 | 1 | - |  |
| holding | 6027 | 5 |  | 0 | 20 | - |  |
| holding | 6028 | 0 |  | -20 | 0 | - |  |
| holding | 6029 | 5 |  | 0 | 10 | - |  |
| holding | 6030 | 0 |  | 0 | 1 | - |  |
| holding | 6031 | 24 |  | 10 | 30 | - |  |
| holding | 6032 | 0 |  | 0 | 1 | - |  |
| holding | 6033 | 3 |  | 0 | 3 | - |  |
| holding | 6034 | 65511 | -25 | -40 | -10 | - |  |
| holding | 6035 | 1 |  | 0 | 1 | - |  |
| holding | 6036 | 0 |  | 0 | 1 | - |  |
| holding | 6037 | 0 |  | 0 | 1 | - |  |
| holding | 6038 | 75 |  | 0 | 480 | - |  |
| holding | 6039 | 10 |  | 0 | 40 | - |  |
| holding | 6040 | 65526 | -10 | -20 | 20 | - |  |
| holding | 6041 | 15 |  | 10 | 25 | - | not the compressor minimum frequency (a write did not move the floor) |
| holding | 6042 | 10 |  | 1 | 20 | - |  |
| holding | 6043 | 60 |  | 30 | 60 | - |  |
| holding | 6044 | 2 |  | 1 | 2 | - |  |
| holding | 6045 | 65531 | -5 | -15 | 5 | - |  |
| holding | 6046 | 15 |  | 10 | 100 | - | compressor minimum frequency, Hz; a write takes effect during a run |
| holding | 6047 | 40 |  | 30 | 120 | - | silent mode level_2 compressor cap, Hz: level_2 runs plateau at this value |
| holding | 6048 | 0 |  | -10 | 15 | - |  |
| holding | 6049 | 400 |  | 300 | 1000 | - |  |
| holding | 6050 | 100 |  | 10 | 100 | 1439 HoldingRegister_6050 | pump speed setting %, panel HoldingRegister_6050 (forum: standby/min/max defaults 30/50/100) |
| holding | 6051 | 500 |  | 200 | 1000 | - |  |
| holding | 6052 | 250 |  | 200 | 500 | - |  |
| holding | 6053 | 850 |  | 300 | 1000 | - | fan speed maximum, rpm: also caps the start-up burst (836 to 844 at 850, 793 at 800) |
| holding | 6054 | 450 |  | 300 | 1000 | - |  |
| holding | 6055 | 40 |  | 20 | 60 | - |  |
| holding | 6056 | 65531 | -5 | -10 | 20 | - |  |
| holding | 6057 | 0 |  | 0 | 1000 | - |  |
| holding | 6058 | 0 |  | 0 | 1000 | - |  |
| holding | 6059 | 0 |  | 0 | 1000 | - |  |
| holding | 6060 | 100 |  | 15 | 100 | - |  |
| holding | 6061 | 65 |  | 30 | 100 | 1440 HoldingRegister_6061 | pump speed setting %, panel HoldingRegister_6061 |
| holding | 6062 | 1 |  | 0 | 1 | - |  |
| holding | 6063 | 3 |  | 0 | 10 | - |  |
| holding | 6064 | 6 |  | -5 | 25 | - |  |
| holding | 6065 | 0 |  | 0 | 480 | - |  |
| holding | 6066 | 150 |  | 0 | 480 | - |  |
| holding | 6067 | 150 |  | 0 | 480 | - |  |
| holding | 6068 | 60 |  | 20 | 100 | - |  |
| holding | 6069 | 400 |  | 0 | 480 | - |  |
| holding | 6070 | 400 |  | 0 | 480 | - |  |
| holding | 6071 | 40 |  | 20 | 100 | - |  |
| holding | 6072 | 400 |  | 0 | 480 | - |  |
| holding | 6073 | 0 |  | 0 | 480 | - |  |
| holding | 6074 | 6 |  | 0 | 100 | - |  |
| holding | 6075 | 247 |  | 1 | 255 | - |  |
| holding | 6076 | 1 |  | 0 | 1 | - |  |
| holding | 6077 | 0 |  | 0 | 3 | - |  |
| holding | 6078 | 1 |  | 0 | 1 | - |  |
| holding | 6079 | 4 |  | 0 | 15 | - |  |
| holding | 6080 | 6 |  | 0 | 15 | - |  |
| holding | 6081 | 5 |  | 0 | 15 | - |  |
| holding | 6082 | 6 |  | 0 | 15 | - |  |
| holding | 6083 | 4 |  | 0 | 15 | - |  |
| holding | 6084 | 60 |  | 30 | 100 | - |  |
| holding | 6085 | 20 |  | 0 | 100 | - |  |
| holding | 6086 | 120 |  | 0 | 120 | - |  |
| holding | 6087 | 1 |  | 0 | 1 | - |  |
| holding | 6088 | 3 |  | 1 | 10 | - |  |
| holding | 6089 | 55 |  | 40 | 90 | - |  |
| holding | 6090 | 25 |  | 20 | 90 | - |  |
| holding | 6091 | 45 |  | 20 | 90 | - |  |
| holding | 6092 | 0 |  | 0 | 60 | - |  |
| holding | 6093 | 60 |  | 0 | 120 | - |  |
| holding | 6094 | 40 |  | 30 | 50 | - |  |
| holding | 6095 | 40 |  | 10 | 100 | - |  |
| holding | 6096 | 65521 | -15 | -30 | 0 | - |  |
| holding | 6097 | 90 |  | 50 | 100 | - |  |
| holding | 6098 | 4 |  | -10 | 40 | - |  |
| holding | 6099 | 1 |  | 0 | 1 | - |  |
| holding | 6100 | 10 |  | 1 | 20 | - |  |
| holding | 6101 | 10 |  | 10 | 100 | - |  |
| holding | 6102 | 4 |  | 1 | 10 | - |  |
| holding | 6103 | 0 |  | 0 | 1 | - |  |
| holding | 6104 | 0 |  | 0 | 3 | - |  |
| holding | 6105 | 10 |  | 2 | 20 | - |  |
| holding | 6106 | 30 |  | 0 | 90 | - |  |
| holding | 6107 | 0 |  | 0 | 1 | - |  |
| holding | 6108 | 0 |  | 0 | 1 | - |  |
| holding | 6109 | 0 |  | 0 | 1 | - |  |
| holding | 6110 | 0 |  | 0 | 2 | - |  |
| holding | 6111 | 0 |  | 0 | 1 | - |  |
| holding | 6112 | 2 |  | 0 | 24 | - |  |
| holding | 6113 | 0 |  | 0 | 1 | - |  |
| holding | 6114 | 1 |  | 0 | 1 | - |  |
| holding | 6115 | 1 |  | 0 | 1 | - |  |
| holding | 6116 | 5 |  | 5 | 120 | - |  |
| holding | 6117 | 120 |  | 5 | 180 | - |  |
| holding | 6118 | 1 |  | 0 | 1 | - |  |
| holding | 6119 | 15 |  | 0 | 50 | - |  |
| holding | 6120 | 0 |  | 0 | 2 | - |  |
| holding | 6121 | 17 |  | 10 | 17 | - |  |
| holding | 6122 | 25 |  | 20 | 29 | - |  |
| holding | 6123 | 0 |  | 0 | 3 | - |  |
| holding | 6124 | 0 |  | 0 | 7 | - |  |
| holding | 6125 | 0 |  | 0 | 1 | - |  |
| holding | 6126 | 0 |  | 0 | 1 | - |  |
| holding | 6127 | 0 |  | 0 | 2 | - |  |
| holding | 6128 | 1 |  | 0 | 1 | - |  |
| holding | 6129 | 70 |  | 0 | 100 | - |  |
| holding | 6130 | 70 |  | 0 | 100 | - |  |
| holding | 6131 | 60 |  | 0 | 100 | - |  |
| holding | 6132 | 55 |  | 0 | 100 | - |  |
| holding | 6133 | 50 |  | 0 | 100 | - |  |
| holding | 6134 | 45 |  | 0 | 100 | - |  |
| holding | 6135 | 55 |  | 0 | 100 | - |  |
| holding | 6136 | 60 |  | 0 | 100 | - |  |
| holding | 6137 | 65 |  | 0 | 100 | - |  |
| holding | 6138 | 70 |  | 0 | 100 | - |  |
| holding | 6139 | 70 |  | 0 | 100 | - |  |
| holding | 6140 | 20 |  | 0 | 100 | - |  |
| holding | 6141 | 20 |  | 0 | 100 | - |  |
| holding | 6142 | 20 |  | 0 | 100 | - |  |
| holding | 6143 | 15 |  | 0 | 100 | - |  |
| holding | 6144 | 10 |  | 0 | 100 | - |  |
| holding | 6145 | 20 |  | 0 | 100 | - |  |
| holding | 6146 | 25 |  | 0 | 100 | - |  |
| holding | 6147 | 25 |  | 0 | 100 | - |  |
| holding | 6148 | 25 |  | 0 | 100 | - |  |
| holding | 6149 | 25 |  | 0 | 100 | - |  |
| holding | 6150 | 0 |  | -10 | 20 | - |  |
| holding | 6151 | 0 |  | -10 | 20 | - |  |
| holding | 6152 | 65535 | -1 | -10 | 20 | - |  |
| holding | 6153 | 65533 | -3 | -10 | 20 | - |  |
| holding | 6154 | 65532 | -4 | -10 | 20 | - |  |
| holding | 6155 | 65531 | -5 | -10 | 20 | - |  |
| holding | 6156 | 60 |  | 0 | 100 | - |  |
| holding | 6157 | 50 |  | 0 | 100 | - |  |
| holding | 6158 | 50 |  | 0 | 100 | - |  |
| holding | 6159 | 35 |  | 0 | 100 | - |  |
| holding | 6160 | 30 |  | 0 | 100 | - |  |
| holding | 6161 | 45 |  | 0 | 100 | - |  |
| holding | 6162 | 20 |  | 0 | 100 | - |  |
| holding | 6163 | 20 |  | 0 | 100 | - |  |
| holding | 6164 | 15 |  | 0 | 100 | - |  |
| holding | 6165 | 10 |  | 0 | 100 | - |  |
| holding | 6166 | 10 |  | 0 | 100 | - |  |
| holding | 6167 | 50 |  | 0 | 100 | - |  |
| holding | 6168 | 50 |  | 0 | 100 | - |  |
| holding | 6169 | 55 |  | 0 | 100 | - |  |
| holding | 6170 | 55 |  | 0 | 100 | - |  |
| holding | 6171 | 70 |  | 0 | 100 | - |  |
| holding | 6172 | 50 |  | 0 | 100 | - |  |
| holding | 6173 | 50 |  | 0 | 100 | - |  |
| holding | 6174 | 55 |  | 0 | 100 | - |  |
| holding | 6175 | 55 |  | 0 | 100 | - |  |
| holding | 6176 | 70 |  | 0 | 100 | - |  |
| holding | 6177 | 18 |  | -10 | 20 | - |  |
| holding | 6178 | 12 |  | -10 | 20 | - |  |
| holding | 6179 | 7 |  | -10 | 20 | - |  |
| holding | 6180 | 5 |  | -10 | 20 | - |  |
| holding | 6181 | 4 |  | -10 | 20 | - |  |
| holding | 6182 | 5 |  | -10 | 20 | - |  |
| holding | 6183 | 0 |  | 0 | 2 | - |  |
| holding | 6184 | 1 |  | 0 | 2 | - |  |
| holding | 6185 | 0 |  | 0 | 2 | - |  |
| holding | 6186 | 2 |  | 0 | 2 | - |  |
| holding | 6187 | 4 |  | 1 | 9 | - |  |
| holding | 6188 | 4 |  | 1 | 9 | - |  |
| holding | 6189 | 3 |  | 1 | 9 | - |  |
| holding | 6190 | 6 |  | 1 | 9 | - |  |
| holding | 6191 | 4 |  | 1 | 9 | - |  |
| holding | 6192 | 4 |  | 1 | 9 | - |  |
| holding | 6193 | 3 |  | 1 | 9 | - |  |
| holding | 6194 | 6 |  | 1 | 9 | - |  |
| holding | 6195 | 3 |  | 0 | 36 | - |  |
| holding | 6196 | 3 |  | 0 | 36 | - |  |
| holding | 6197 | 25 |  | -5 | 46 | - |  |
| holding | 6198 | 35 |  | -5 | 46 | - |  |
| holding | 6199 | 16 |  | 5 | 25 | - |  |
| holding | 6200 | 10 |  | 5 | 25 | - |  |
| holding | 6201 | 65531 | -5 | -25 | 35 | - |  |
| holding | 6202 | 7 |  | -25 | 35 | - |  |
| holding | 6203 | 35 |  | 18 | 75 | - |  |
| holding | 6204 | 28 |  | 18 | 75 | - |  |
| holding | 6205 | 5 |  | 0 | 120 | - |  |
| holding | 6206 | 2 |  | 0 | 120 | - |  |
| holding | 6207 | 5 |  | 2 | 10 | - |  |
| holding | 6208 | 0 |  | -10 | 0 | - |  |
| holding | 6209 | 0 |  | 0 | 1 | - |  |
| holding | 6210 | 0 |  | 0 | 3 | - |  |
| holding | 6211 | 13 |  | 5 | 50 | - |  |
| holding | 6212 | 10 |  | 5 | 30 | - |  |
| holding | 6213 | 30 |  | 5 | 100 | - |  |
| holding | 6214 | 60 |  | 5 | 100 | - |  |
| holding | 6215 | 30 |  | 5 | 100 | - |  |
| holding | 6216 | 95 |  | 50 | 100 | - |  |
| holding | 6217 | 20 |  | 5 | 50 | - |  |
| holding | 6218 | 0 |  | -50 | 50 | - |  |
| holding | 6219 | 0 |  | -50 | 50 | - |  |
| holding | 6220 | 0 |  | -50 | 50 | - |  |
| holding | 6221 | 15 |  | 10 | 100 | - |  |
| holding | 6222 | 17 |  | 10 | 100 | - |  |
| holding | 6223 | 19 |  | 10 | 100 | - |  |
| holding | 6224 | 20 |  | 10 | 100 | - |  |
| holding | 6225 | 22 |  | 10 | 100 | - |  |
| holding | 6226 | 3 |  | 1 | 60 | - |  |
| holding | 6227 | 5 |  | 1 | 60 | - |  |
| holding | 6228 | 10 |  | 1 | 60 | - |  |
| holding | 6229 | 5 |  | 1 | 60 | - |  |
| holding | 6230 | 10 |  | 10 | 600 | - |  |
| holding | 6231 | 450 |  | 200 | 1000 | 1444 H_FAN_SPEED_1_6231 | H_FAN_SPEED_1, rpm (panel) |
| holding | 6232 | 570 |  | 200 | 1000 | 1445 H_FAN_SPEED_2_6232 | H_FAN_SPEED_2, rpm (panel) |
| holding | 6233 | 650 |  | 200 | 1000 | 1446 H_FAN_SPEED_3_6233 | H_FAN_SPEED_3, rpm (panel) |
| holding | 6234 | 500 |  | 200 | 1000 | - | second fan table step 1 (cooling?) |
| holding | 6235 | 550 |  | 200 | 1000 | - | second fan table step 2 |
| holding | 6236 | 600 |  | 200 | 1000 | - | second fan table step 3 |
| holding | 6237 | 1 |  | 1 | 2 | - |  |
| holding | 6238 | 2 |  | 0 | 6 | - |  |
| holding | 6239 | 40 |  | 30 | 80 | - |  |
| holding | 6240 | 25 |  | 10 | 50 | - |  |
| holding | 6241 | 10 |  | 5 | 20 | - |  |
| holding | 6242 | 50 |  | 0 | 100 | - |  |
| holding | 6243 | 7 |  | -10 | 20 | - |  |
| holding | 6244 | 400 |  | 200 | 1000 | 1443 H_FAN_SPEED_0_6244 | H_FAN_SPEED_0, rpm (panel) |
| holding | 6245 | 500 |  | 200 | 1000 | - | possibly the counterpart of 6244 |
| holding | 6246 | 2 |  | 0 | 2 | - |  |
| holding | 6247 | 1 |  | 0 | 1 | - |  |
| holding | 6248 | 95 |  | 80 | 120 | - |  |
| holding | 6249 | 110 |  | 100 | 150 | - |  |
| holding | 6250 | 105 |  | 100 | 150 | - |  |
| holding | 6251 | 0 |  | 0 | 1 | - |  |
| holding | 6252 | 60 |  | 25 | 75 | - |  |
| holding | 6253 | 0 |  | 0 | 1 | - |  |
| holding | 6254 | 0 |  | 0 | 1 | - |  |
| holding | 6255 | 0 |  | 0 | 1 | - |  |
| holding | 6256 | 0 |  | 0 | 1 | - |  |
| holding | 6257 | 30 |  | 5 | 60 | - |  |
| holding | 6258 | 0 |  | 0 | 10 | - |  |
| holding | 6259 | 0 |  | 0 | 1 | - |  |
| holding | 6260 | 0 |  | 0 | 1 | - |  |
| holding | 6261 | 30 |  | 0 | 240 | - |  |
| holding | 6262 | 30 |  | 0 | 240 | - |  |
| holding | 6263 | 30 |  | 0 | 240 | - |  |
| holding | 6264 | 30 |  | 0 | 240 | - |  |
| holding | 6265 | 5 |  | 1 | 30 | - |  |
| holding | 6266 | 60 |  | 0 | 60 | - |  |
| holding | 6267 | 12 |  | 1 | 15 | - |  |
| holding | 6268 | 7 |  | 1 | 15 | - |  |
| holding | 6269 | 330 |  | 300 | 700 | - |  |
| holding | 6270 | 30 |  | 20 | 60 | - |  |
| holding | 6271 | 100 |  | 50 | 100 | 1441 HoldingRegister_6271 | pump speed setting %, panel HoldingRegister_6271 |
| holding | 6272 | 0 |  | 0 | 4 | - |  |
| holding | 6273 | 0 |  | 0 | 100 | 1442 HoldingRegister_6273 | pump speed setting %, panel HoldingRegister_6273 |
| holding | 6274 | 0 |  | 0 | 1 | - |  |

## Scan files

- `docs/scans/2026-09-17_holding_6000-6499.tsv`: the 6000 block.
- `docs/scans/2026-09-17_holding_full.tsv`, `2026-09-17_input_full.tsv`: full discovery of both register spaces (fine ranges plus stride-16 sweeps).
- `docs/scans/2026-09-17_holding_stride8.tsv`, `2026-09-17_input_stride8.tsv`: stride-8 passes over 2300 to 2999 and 6275 / 6500 to 8191.
- `docs/scans/2026-09-17_coil.tsv`, `2026-09-17_discrete.tsv`: function codes 01 and 02, rejected.
