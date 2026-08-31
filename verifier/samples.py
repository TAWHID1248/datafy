"""A bundled sample CSV so users can try the full workflow with one click.

Deliberately messy: mixed international + bare national numbers, a duplicate,
a malformed value, a blank, and extra columns — so every downstream path
(normalization, dedup, flagging, matching) is exercised.
"""

SAMPLE_CSV = """name,phone,city,segment
Alice Rahman,+8801712345678,Dhaka,vip
Bob Karim,01912345679,Chittagong,new
Carol Smith,+14155552671,San Francisco,vip
David Lee,4155552672,Oakland,new
Eve Duplicate,+8801712345678,Dhaka,vip
Frank Bad,not-a-number,Unknown,new
Grace Blank,,Sylhet,new
Hasan Ali,+442071838750,London,vip
Ivy Chen,+8613800138000,Beijing,new
Jamal Uddin,01812345670,Khulna,vip
"""

SAMPLE_FILENAME = "sample_contacts.csv"
