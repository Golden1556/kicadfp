EESchema Schematic File Version 2  date Ср 02.09.26 19:52:23
LIBS:demo
LIBS:power
LIBS:device
LIBS:transistors
LIBS:conn
LIBS:linear
LIBS:regul
LIBS:74xx
LIBS:cmos4000
LIBS:adc-dac
LIBS:memory
LIBS:xilinx
LIBS:special
LIBS:microcontrollers
LIBS:dsp
LIBS:microchip
LIBS:analog_switches
LIBS:motorola
LIBS:texas
LIBS:intel
LIBS:audio
LIBS:interface
LIBS:digital-audio
LIBS:philips
LIBS:display
LIBS:cypress
LIBS:siliconi
LIBS:opto
LIBS:atmel
LIBS:contrib
LIBS:valves
LIBS:demo-cache
EELAYER 25  0
EELAYER END
$Descr A3 16535 11700
encoding utf-8
Sheet 1 1
Title "Demo of every schematic item"
Date "2011-04-29"
Rev "A"
Comp "RSREU"
Comment1 "comment 1"
Comment2 ""
Comment3 ""
Comment4 "comment 4 \"quoted\""
$EndDescr
$Comp
L NAND2 DD1
U 1 1 5C3DB359
P 3000 2000
F 0 "DD1" H 3000 1650 60  0000 C CNN
F 1 "NAND2" H 3000 2350 60  0000 C CNN
F 4 "74LS00" H 3000 2450 50  0001 C CNN "Part"
	1    3000 2000
	1    0    0    -1  
$EndComp
$Comp
L NAND2 DD1
U 2 1 5C3DB35A
P 3000 3000
F 0 "DD1" H 3000 2650 60  0000 C CNN
F 1 "NAND2" H 3000 3350 60  0000 C CNN
F 4 "74LS00" H 3000 3450 50  0001 C CNN "Part"
	2    3000 3000
	1    0    0    -1  
$EndComp
$Comp
L NAND2 DD3
U 1 2 5C3DB35B
P 3000 5000
F 0 "DD3" H 3000 4650 60  0000 C CNN
F 1 "NAND2" H 3000 5350 60  0000 C CNN
F 4 "74LS00" H 3000 5450 50  0001 C CNN "Part"
	1    3000 5000
	1    0    0    -1  
$EndComp
$Comp
L NAND2 DD1
U 3 1 5C3DB35C
P 5000 2000
F 0 "DD1" H 5350 2000 60  0000 C CNN
F 1 "NAND2" H 4650 2000 60  0000 C CNN
F 4 "74LS00" H 4550 2000 50  0001 C CNN "Part"
	3    5000 2000
	0    1    1    0   
$EndComp
$Comp
L NAND2 DD1
U 4 1 5C3DB35D
P 5000 3500
F 0 "DD1" H 5000 3150 60  0000 C CNN
F 1 "NAND2" H 5000 3850 60  0000 C CNN
F 4 "74LS00" H 5000 3950 50  0001 C CNN "Part"
	4    5000 3500
	-1   0    0    -1  
$EndComp
$Comp
L C C1
U 1 1 5C3DB35E
P 7000 2500
F 0 "C1" H 6900 2400 60  0000 C CNN
F 1 "C" H 7100 2400 60  0000 C CNN
	1    7000 2500
	0    -1   -1   0   
$EndComp
$Comp
L CLKIN DD2
U 1 1 5C3DB35F
P 7000 4500
F 0 "DD2" H 7000 4220 60  0000 C CNN
F 1 "CLKIN" H 7000 4780 60  0000 C CNN
F 4 "buffer" H 7000 5200 60  0000 C CNN "Note"
	1    7000 4500
	-1   0    0    -1  
$EndComp
$Comp
L VCC #PWR01
U 1 1 5C3DB360
P 2000 1000
F 0 "#PWR01" H 2000 750 60  0001 C CNN
F 1 "VCC" H 2000 650 60  0000 C CNN
	1    2000 1000
	1    0    0    -1  
$EndComp
$Comp
L GND #PWR02
U 1 1 5C3DB361
P 2000 4500
F 0 "#PWR02" H 2000 4750 60  0001 C CNN
F 1 "GND" H 2000 4850 60  0000 C CNN
	1    2000 4500
	1    0    0    -1  
$EndComp
Wire Wire Line
	3500 2000 4000 2000
Wire Wire Line
	4000 2000 5100 2000
Wire Wire Line
	5100 2000 5100 1500
Wire Wire Line
	3500 3000 4000 3000
Wire Wire Line
	4000 3000 4000 3400
Wire Wire Line
	4000 3400 5500 3400
Wire Wire Line
	2500 1900 2000 1900
Wire Wire Line
	2000 1900 2000 1000
Wire Wire Line
	2500 3100 2000 3100
Wire Wire Line
	2000 3100 2000 4500
Wire Wire Line
	7000 2700 6000 2700
Wire Wire Line
	6000 2700 6000 2500
Wire Wire Line
	6000 2500 5000 2500
Wire Wire Line
	2000 1000 2000 1900
Wire Wire Line
	2000 1900 2500 1900
Wire Bus Line
	8500 1000 8500 4000
Entry Wire Line
	8500 1500 8600 1600
Entry Wire Line
	8500 2500 8400 2600
Text Label 8500 1000 1    60   ~ 0
DATA[0..7]
Text Label 8600 1600 0    60   ~ 0
DATA0
Text GLabel 4000 2000 0    60   Input ~ 0
CLK_IN
Text HLabel 9000 3000 2    60   Output ~ 0
TO_SUB
Text Notes 1000 6000 0    80   ~ 0
Demo schematic\nsecond line
NoConn ~ 2500 2100
NoConn ~ 2500 2900
$Sheet
S 10000 2500 1500 1000
U 5C3DB362
F0 "sub" 60
F1 "sub.sch" 60
F2 "TO_SUB" I L 10000 3000 60 
F3 "OUT" O R 11500 3200 60 
$EndSheet
Connection ~ 2000 1900
Connection ~ 4550 2000
$EndSCHEMATC
