results = db.search_by_device_names({
    'label': 'venous vs arterial thrombectomy cohorts', 
    'criteria': {
        'venous thrombectomy': [
            ['venous', 'thrombectomy'],     # (venous AND thrombectomy)...
            ['venous', 'angiojet'],         # OR (venous AND angiojet)...
            ['venous', 'argon', 'cleaner'], # OR (venous AND argon AND cleaner)...
            ['vein', 'thrombectomy'],       # ...etc.
            ['vein', 'angiojet'],
            ['vein', 'argon', 'cleaner'],
            ['dvt', 'thrombectomy'],
            ['dvt', 'angiojet'],
            ['dvt', 'argon', 'cleaner']
        ],

        # next group matches only records not matched by first group
        'arterial thrombectomy': [ 
            ['arterial', 'thrombectomy'],
            ['arterial', 'angiojet'],
            ['arterial', 'argon', 'cleaner'],
            ['artery', 'thrombectomy'],
            ['artery', 'angiojet'],
            ['artery', 'argon', 'cleaner'],
            ['coronary', 'thrombectomy'],
            ['coronary', 'angiojet'],
            ['coronary', 'argon', 'cleaner']
        ], 

        # third group matches only records not matched by first two groups
        'ambiguous thrombectomy': [ 
            ['thrombectomy'],
            ['angiojet'],
            ['argon', 'cleaner']
        ] 
    }
})