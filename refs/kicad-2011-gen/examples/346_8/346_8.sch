EESchema Schematic File Version 2  date Ср 02.09.26 19:52:23
LIBS:My_lib
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
LIBS:346_8-cache
EELAYER 25  0
EELAYER END
$Descr A4 11700 8267
encoding utf-8
Sheet 1 1
Title "Лабораторная работа 3, бригада 346_8"
Date ""
Rev ""
Comp ""
Comment1 ""
Comment2 ""
Comment3 ""
Comment4 ""
$EndDescr
$Comp
L CONNECT X1
U 1 1 5C3DB359
P 1600 3150
F 0 "X1" H 1600 1720 60  0000 C CNN
F 1 "CONNECT" H 1600 4580 60  0001 C CNN
F 2 "snp8" H 1600 3150 60  0001 C CNN
	1    1600 3150
	1    0    0    -1  
$EndComp
$Comp
L K555TB6 DD1
U 1 1 5C3DB35A
P 6300 1950
F 0 "DD1" H 6300 1370 60  0000 C CNN
F 1 "K555TB6" H 6300 2530 60  0001 C CNN
F 2 "dip14" H 6300 1950 60  0001 C CNN
	1    6300 1950
	1    0    0    -1  
$EndComp
$Comp
L K555TB6 DD1
U 2 1 5C3DB35B
P 6300 4350
F 0 "DD1" H 6300 3770 60  0000 C CNN
F 1 "K555TB6" H 6300 4930 60  0001 C CNN
F 2 "dip14" H 6300 4350 60  0001 C CNN
	2    6300 4350
	1    0    0    -1  
$EndComp
$Comp
L REZ R1
U 1 1 5C3DB35C
P 4900 5050
F 0 "R1" H 4900 4915 60  0000 C CNN
F 1 "REZ" H 4900 5185 60  0001 C CNN
F 2 "mlt" H 4900 5050 60  0001 C CNN
	1    4900 5050
	1    0    0    -1  
$EndComp
$Comp
L GND #PWR01
U 1 1 5C3DB35D
P 2750 2150
F 0 "#PWR01" H 2750 1850 60  0001 C CNN
F 1 "GND" H 2750 1750 60  0001 C CNN
	1    2750 2150
	-1   0    0    1   
$EndComp
$Comp
L GND #PWR02
U 1 1 5C3DB35E
P 4350 5500
F 0 "#PWR02" H 4350 5800 60  0001 C CNN
F 1 "GND" H 4350 5900 60  0001 C CNN
	1    4350 5500
	1    0    0    -1  
$EndComp
$Comp
L VCC #PWR03
U 1 1 5C3DB35F
P 2150 5100
F 0 "#PWR03" H 1850 5100 60  0001 C CNN
F 1 "VCC" H 1750 5100 60  0001 C CNN
	1    2150 5100
	0    1    1    0   
$EndComp
Wire Wire Line
	2500 2250 2750 2250
Wire Wire Line
	2750 2250 2750 2150
Wire Wire Line
	2500 2550 3950 2550
Wire Wire Line
	2500 3150 3950 3150
Wire Wire Line
	2500 3450 3950 3450
Wire Wire Line
	4350 1650 5700 1650
Wire Wire Line
	4350 2050 5700 2050
Wire Wire Line
	4350 4050 5700 4050
Wire Wire Line
	2500 2850 4900 2850
Wire Wire Line
	4900 2850 4900 2250
Wire Wire Line
	4900 2250 5700 2250
Wire Wire Line
	2500 3750 4550 3750
Wire Wire Line
	4550 3750 4550 1850
Wire Wire Line
	4550 1850 5700 1850
Wire Wire Line
	4550 3750 4550 4250
Wire Wire Line
	4550 4250 5700 4250
Wire Wire Line
	6900 1650 7300 1650
Wire Wire Line
	7300 1650 7300 3150
Wire Wire Line
	7300 3150 5100 3150
Wire Wire Line
	5100 3150 5100 4450
Wire Wire Line
	5100 4450 5700 4450
Wire Wire Line
	6900 4050 7300 4050
Wire Wire Line
	7300 4050 7300 5900
Wire Wire Line
	7300 5900 3550 5900
Wire Wire Line
	3550 5900 3550 4050
Wire Wire Line
	3550 4050 2500 4050
Wire Wire Line
	5700 4650 5300 4650
Wire Wire Line
	5300 4650 5300 5050
Wire Wire Line
	4500 5050 4350 5050
Wire Wire Line
	4350 5050 4350 5500
Wire Wire Line
	2500 4350 2550 4350
Wire Wire Line
	2550 4350 2550 5100
Wire Wire Line
	2550 5100 2150 5100
Wire Bus Line
	4150 1200 4150 5500
Entry Wire Line
	4150 2350 3950 2550
Entry Wire Line
	4150 2950 3950 3150
Entry Wire Line
	4150 3250 3950 3450
Entry Wire Line
	4150 1450 4350 1650
Entry Wire Line
	4150 1850 4350 2050
Entry Wire Line
	4150 3850 4350 4050
Text Label 3550 2550 0    60   ~ 0
1
Text Label 3550 3150 0    60   ~ 0
2
Text Label 3550 3450 0    60   ~ 0
3
Text Label 4400 1650 0    60   ~ 0
1
Text Label 4400 2050 0    60   ~ 0
3
Text Label 4400 4050 0    60   ~ 0
2
NoConn ~ 6900 2250
NoConn ~ 6900 4650
Connection ~ 4550 3750
$EndSCHEMATC
