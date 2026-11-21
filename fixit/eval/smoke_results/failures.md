# Failure log

## macbook_cable_clean.mp4 — baseline
- expected: magsafe (frayed Apple MagSafe MacBook charger cable)
- baseline query: Apple MagSafe power adapter
  1. Apple (45-Watt) MagSafe 2 Power Adapter with Folding Wall Plug - White (A1436) (kw=True, fit=None) — judge: This is a MagSafe 2 power adapter, which is not compatible with an original MagSafe connector.
  2. Apple 85W MagSafe 2 Power Adapter (New in Box) (kw=True, fit=None) — judge: This is a MagSafe 2 power adapter, which is not compatible with an original MagSafe connector.
  3. Apple 45W MagSafe 2 Power Adapter with 3-Prong Wall Cable - White (A1436) (kw=True, fit=None) — judge: This is a MagSafe 2 power adapter, which is not compatible with an original MagSafe connector.

## macbook_cable_messy.mp4 — baseline
- expected: magsafe (frayed Apple MagSafe MacBook charger cable)
- baseline query: ballpoint pens
  1. Smooth Oil Ink Ballpoint Pen 0.38 mm - Black (kw=False, fit=None) — judge: This is a ballpoint pen, not a MagSafe charger cable.
  2. Pentel Calme Ballpoint Pen - 0.35mm (kw=False, fit=None) — judge: This is a ballpoint pen, not a MagSafe charger cable.
  3. Penco Perfection Ballpoint Pen (kw=False, fit=None) — judge: This is a ballpoint pen, not a MagSafe charger cable.

## aerator_messy.mp4 — baseline
- expected: aerator (worn swivel faucet aerator)
- baseline query: garden hose quick connector
  1. GORILLA EASY CONNECT® Solid Brass Quick Connect Set with SecureLock™ - Standard ¾ Inch GHT Fittings for Garden Hoses and Faucets (kw=False, fit=None) — judge: This is a quick connect set for garden hoses, not a faucet aerator.
  2. 5 Piece Quick Connect Starter Set 18270 (kw=False, fit=None) — judge: This is a quick connect starter set for garden hoses, not a faucet aerator.
  3. Vego Quick Connector Set V1 - Set of 6 (kw=False, fit=None) — judge: This is a quick connector set for hose reels and nozzles, not a faucet aerator.

## brakepads_messy.mp4 — baseline
- expected: brake pad (worn metallic disc brake pads)
- baseline query: bicycle disc brake pads
  1. Shimano J03A Resin Disc Brake Pads (kw=True, fit=None) — judge: These are resin disc brake pads, whereas the broken part is metallic disc brake pads.
  2. SRAM Code / DB8 / G2 RE / Guide RE / Motive – Factory Racing Organic Disc Brake Pads | Gorilla Brakes (kw=True, fit=None) — judge: These are organic disc brake pads, whereas the broken part is metallic disc brake pads.
  3. Disc Brake Pads (kw=True, fit=None) — judge: The product does not specify that it is a metallic disc brake pad and appears to be for specific S4 models.

## real_bulb_burnout.mp4 — full
- expected: bulb (incandescent light bulb whose filament burns out: needs a replacement bulb)
- diagnosed: DIY electrical experiment setup (black SLA battery, alligator clip leads, aluminum foil, and clear bottle with red rubber bands) / Improvised filament and exposed contact at left end of clear cylinder → buy: Replace the improvised foil-and-filament assembly with a proper low-voltage bulb socket, compatible 12V bulb, and an inline fuse. (conf 0.35)
- queries: ['12V miniature bulb socket holder with wire leads', 'insulated alligator clip test leads', 'inline blade fuse holder 12V']; uncertain: ['No brand, model, voltage, or Ah rating is readable on the black battery.', 'The exact material of the glowing element at the left tip (e.g., graphite, nichrome wire, or small filament) cannot be identified.', 'No audio is present to confirm whether a component failed or if this is an intentional science demonstration.']
  1. Screw-In E12 Mini Bulb Holder, 5 Pack Light Beads Lamp Bases Socket Circuit Electrical Experiment Lighting DIY Accessories, White (kw=True, fit=0.554) — judge: This is a bulb holder/socket, not a replacement bulb.
  2. G4 Bulb Socket, AC/DC 12-30V 30cm Long LED Lamp Base Holder, Plastic Black, Pack of 10 (kw=True, fit=0.564) — judge: This is a bulb socket/holder, not a replacement bulb.
  3. Inline Mini Blade Fuse Holder - (ATM) Automotive Fuse Holder Weatherproof (kw=False, fit=0.403) — judge: This is an automotive fuse holder, not a replacement bulb.

## real_flickering_bulb.mp4 — full
- expected: bulb (flickering light bulb in a ceiling fixture: needs a replacement bulb)
- diagnosed: Ceiling light socket fixture with LED bulb / LED bulb diffuser dome / ceiling fixture shade (possibly damaged socket edge) → buy: Replacement LED bulb (matching the socket base) or a complete flush-mount LED ceiling light fixture to cover the exposed base and unpainted ring (conf 0.45)
- queries: ['flush mount LED ceiling light fixture', 'E27 A19 LED bulb cool white', 'B22 bayonet LED bulb cool white']; uncertain: ['No brand, model number, voltage, or wattage markings are readable due to glare and distance.', 'Socket connector type (E26/E27 screw vs. B22 bayonet vs. integrated LED puck) cannot be verified while the bulb is lit and installed.', 'No spoken audio explains whether the bulb is flickering/dim, missing its diffuser dome, or missing a fixture cover.']
  1. 13 inch Flush Mount LED Ceiling Light Fixture, 2700K/3000K/3500K/4000K/5000K Adjustable Ceiling Lights, Brushed Nickel Saturn Dimmable Lighting for Hallway Bathroom Kitchen or Stairwell, ETL Listed (kw=False, fit=0.817) — judge: This is a complete ceiling light fixture, not a replacement bulb.
  2. Dimmable Wood LED Flush Mount Ceiling Light, 2700K-6000K Selectable Modern Round Close to Ceiling Lighting Fixtures, Minimalist White Ceiling Lamp for Living Room, Bedroom, Laundry Room, 15.8" (kw=False, fit=0.746) — judge: This is a complete ceiling light fixture, not a replacement bulb.
  3. Contemporary LED Flush Mount Ceiling Fixture - Modern Bright Light (kw=False, fit=0.666) — judge: This is a complete ceiling light fixture, not a replacement bulb.

## real_flickering_bulb.mp4 — baseline
- expected: bulb (flickering light bulb in a ceiling fixture: needs a replacement bulb)
- baseline query: recessed downlight fixture
  1. NICOR 5/6in. 878Lm LED Downlight in White w/ Baffle, 3000K Round Recessed Light (kw=True, fit=None) — judge: This is a recessed downlight retrofit fixture, not a replacement light bulb.
  2. Feit Electric LEDR56HO/6WYCA Dimmable Recessed Downlight, White (kw=False, fit=None) — judge: This is a recessed downlight fixture, not a replacement light bulb.
  3. RAB R4R89FA120WB ADJUSTABLE CCT LED RECESSED DOWNLIGHT, 8W, 120V, 4-INCH, WHITE (kw=False, fit=None) — judge: This is a recessed downlight retrofit fixture, not a replacement light bulb.

## real_worn_bike_rim.mp4 — full
- expected: rim (bicycle rim worn through by rim brakes after 75,000 miles (handlebar-cam ride footage; failure is hard to see): needs a replacement rim or wheel)
- diagnosed: Road bicycle with drop handlebars and exposed-cable STI shifters / Unconfirmed drivetrain or rear-wheel component (likely bicycle chain, derailleur hanger, or spoke; not visible on camera)  → buy: Confirm the failed part visually first; if the chain snapped, buy a speed-matched bicycle chain and quick-link (or a model-specific derailleur hanger / spoke if one of those failed). (conf 0.2)
- queries: ['road bicycle chain speed matched', 'bicycle chain quick link', 'road bike rear derailleur hanger']; uncertain: ['The handlebar-mounted camera faces forward for the entire clip, so the broken component is never visible in frame.', 'Bicycle brand, model, and drivetrain speed count cannot be read.', 'While a snapped chain under climbing load is most consistent with the sound and inspection posture, a broken spoke, cassette tooth, pedal/crank issue, or derailleur hanger failure cannot be ruled out.']
  1. Shimano Bicycle Chain Quick-Links - Pack of 2 (kw=False, fit=0.306) — judge: This is a bicycle chain quick-link, not a replacement rim or wheel.
  2. Z8.3 (kw=False, fit=0.246) — judge: This is a bicycle chain, not a replacement rim or wheel.
  3. Shimano CN-HG53 9-speed Chain (kw=False, fit=0.239) — judge: This is a 9-speed bicycle chain, not a replacement rim or wheel.

## real_worn_bike_rim.mp4 — baseline
- expected: rim (bicycle rim worn through by rim brakes after 75,000 miles (handlebar-cam ride footage; failure is hard to see): needs a replacement rim or wheel)
- baseline query: road bike brake lever hood
  1. Shimano GRX ST-RX810 Brake Shift Lever Hoods (Shifter Hood Set) (kw=False, fit=None) — judge: This is a set of brake shift lever hoods, not a replacement rim or wheel.
  2. Brake Lever Hoods for Shimano Super Road Lever (kw=False, fit=None) — judge: These are brake lever hoods, not a replacement rim or wheel.
  3. Road Brake Lever Hoods (kw=False, fit=None) — judge: These are brake lever hoods, not a replacement rim or wheel.

## kitchen_blender_burnt_motor.mp4 — full
- expected: blender (blender base with burnt-out motor windings: needs a replacement blender motor/base or a new blender)
- diagnosed: Electric motor armature (rotor assembly with copper windings and laminated core shaft, brand and appliance unknown) / Armature assembly (no specific damaged component visible in frame) → buy: Exact OEM replacement motor armature matching the host tool or appliance model number, or the complete motor assembly (conf 0.45)
- queries: ['OEM replacement electric motor armature rotor', 'universal motor armature assembly', 'electric motor rotor shaft copper winding replacement']; uncertain: ['No brand, model number, or rating label is visible in any frame', 'No audio is present to identify the appliance or reported failure symptom', 'No clear physical damage is visible in the clip; the commutator, brushes, and bearings are out of frame', 'Exact dimensional and electrical specs cannot be determined without measurements or the host device model']
  1. Dewalt n899443 Armature Assembly Replacement Part (kw=False, fit=0.234) — judge: This is an armature assembly for DEWALT power tools, not a blender motor/base or a new blender.
  2. Bosch Armature (Rotor) 2609120337 for GBM 6RE (kw=False, fit=0.231) — judge: This is an armature rotor for a Bosch GBM 6RE power tool, not a blender motor/base or a new blender.
  3. Milwaukee 16-30-0210 Armature Rotor For Electric Tool Motors (kw=False, fit=0.209) — judge: This is an armature rotor for Milwaukee electric tool motors, not a blender motor/base or a new blender.

## kitchen_blender_burnt_motor.mp4 — baseline
- expected: blender (blender base with burnt-out motor windings: needs a replacement blender motor/base or a new blender)
- baseline query: electric motor armature
  1. 12V Armature for Hitachi - New Electric Motor Part, 215.5mm Length (kw=False, fit=None) — judge: This is a 12V armature for a Hitachi electric motor, not a blender motor/base or a new blender.
  2. Electric Motor Armature for Power Tool Repair (kw=False, fit=None) — judge: This is an electric motor armature for power tool repair, not a blender.
  3. 12V CW Armature for Bosch, New Electric Motor Part, 10 Splines, 300-24074 (kw=False, fit=None) — judge: This is a 12V armature for a Bosch electric motor, not a blender motor/base or a new blender.

## kitchen_espresso_group_gasket.mp4 — full
- expected: gasket (espresso machine group head being serviced; worn group head gasket: needs a replacement group head gasket)
- diagnosed: Black rubber seal / gasket ring in labeled bag (background chrome assembly) / Black rubber ring / flat gasket or O-ring (labeled R4.5 on bag) → buy: Matching black rubber gasket or O-ring matching the exact inner diameter, outer diameter, and cross-section thickness of the ring labeled R4.5 (conf 0.45)
- queries: ['R4.5 rubber gasket ring seal', 'black rubber flat gasket O-ring replacement', 'chrome hardware rubber seal ring']; uncertain: ['No audio or narration is present to identify the chrome machine or device in the background', 'The meaning of the handwritten R4.5 label (part code, internal bin number, or dimension) cannot be confirmed visually', 'Exact dimensions (inner diameter, outer diameter, and cross-section profile—flat washer vs. round O-ring) cannot be measured without a scale or calipers']
  1. Custom Ring Gaskets & Seals (kw=True, fit=0.721) — judge: This is a custom gasket cutting service for pipe flanges and housings, not a specific espresso machine group head gasket.
  2. Nitrile O-Ring Repair Kit – 1020-Piece Assorted Sealing Ring Set (kw=False, fit=0.545) — judge: This is a generic assorted O-ring repair kit, not a specific replacement group head gasket for an espresso machine.
  3. Rubber Ring Gasket (kw=True, fit=0.388) — judge: This is a generic rubber ring gasket with no indication of compatibility with an espresso machine group head.

## kitchen_espresso_group_gasket.mp4 — baseline
- expected: gasket (espresso machine group head being serviced; worn group head gasket: needs a replacement group head gasket)
- baseline query: R45 rubber O-ring
  1. R45 O-Ring Kit (kw=False, fit=None) — judge: This is an O-ring kit for a bicycle hub, not an espresso machine group head gasket.
  2. NBR Rubber O-Ring Seal Assortment (kw=False, fit=None) — judge: This is a generic O-ring assortment, not a specific replacement group head gasket for an espresso machine.
  3. Robot Coupe - (DA) O-Ring, R30, R45 - 507050 (kw=False, fit=None) — judge: This is an O-ring for a Robot Coupe food processor, not an espresso machine group head gasket.

## kitchen_rusty_cabinet_hinge.mp4 — baseline
- expected: hinge (rusted, broken cabinet/door hinge: needs a replacement hinge)
- baseline query: heavy duty gate strap hinge
  1. Heavy Duty Lift-Off Strap Hinge (kw=True, fit=None) — judge: This is a heavy-duty lift-off strap hinge designed for gates, not a standard cabinet or door hinge.
  2. Strap Hinge - Heavy Duty for Gates - 18" Inch - Up to 200 lbs - Cast Iron - Black Powder Coat Finish - Sold Individually (kw=True, fit=None) — judge: This is an 18-inch heavy-duty cast iron strap hinge designed for large gates, which is not compatible with a standard cabinet or door.
  3. 13” Heavy Duty Gate Strap Hinge – 900 lb Bolt or Weld-On (kw=True, fit=None) — judge: This is a 13-inch heavy-duty bolt or weld-on gate strap hinge rated for 900 lbs, which is not suitable for a cabinet or standard door.

## kitchen_immersion_blender_coupling.mp4 — full
- expected: blender (Bosch MaxoMixx immersion (hand) blender with broken plastic coupling latch: needs a replacement blending shaft/attachment or hand blender)
- diagnosed: Bosch MaxoMixx 800 W hand blender (immersion blender) lower locking assembly / Attachment release button spring ring (or grey inner locking sleeve assembly) (unconfirmed due to lack of visible fracture or audio explanation; could also be an internal motor coupling issue given the full disassembly of the nose cone). → buy: Bosch MaxoMixx 800W attachment release button ring and/or grey locking sleeve (confirm exact E-Nr from the black collar before ordering). (conf 0.6)
- queries: ['Bosch MaxoMixx 800W release button ring spare part', 'Bosch MaxoMixx 800W locking sleeve coupling housing', 'Bosch MSM8 hand blender attachment release button']; uncertain: ["No audio is available to confirm the user's exact symptom or why the unit was disassembled.", 'The exact E-Nr / MSM8xxx model number printed on the black collar of the silver sleeve is too blurry to read.', 'No obvious broken tab or snapped plastic is clearly visible; the matchstick wedged in the release ring may indicate weakened spring arms, a repair brace, or a size reference.']
  1. Bosch Button - 00604771 (kw=False, fit=0.418) — judge: A button is not a replacement blending shaft/attachment or hand blender.
  2. Bosch Ring - 00608828 (kw=False, fit=0.387) — judge: A ring is not a replacement blending shaft/attachment or hand blender.
  3. Bosch Locking Sleeve - 2600114012 (kw=False, fit=0.27) — judge: A locking sleeve is not a replacement blending shaft/attachment or hand blender.

## kitchen_immersion_blender_coupling.mp4 — baseline
- expected: blender (Bosch MaxoMixx immersion (hand) blender with broken plastic coupling latch: needs a replacement blending shaft/attachment or hand blender)
- baseline query: Bosch MaxoMixx 800W release button ring
  1. Bosch Release Button - 2608000173 (kw=False, fit=None) — judge: This is a generic Bosch release button, not a replacement blending shaft, attachment, or hand blender for a Bosch MaxoMixx immersion blender.
  2. Bosch Door Ring - 00747800 (kw=False, fit=None) — judge: This is a door ring for an appliance, not a replacement part for a hand blender.
  3. Bosch 00648876 Genuine OEM Microwave Rotating Ring (kw=False, fit=None) — judge: This is a microwave rotating ring, not a replacement part for a hand blender.
