
@classmethod
def _key_values(cls, 
                    key1:str, key2:str,*,data:list 
                    ) -> list[dict[str,str]]:
        pair:list[dict[str,str|int]] = []
        cls.seen_value1 = []
        cls.seen_value2 = []
    
        for entry in data:
           for key in entry:
               if key == key1:
                   if not entry[key]:
                        continue
                   else:
                       if not entry[key] in cls.seen_value1 and entry[key] != "" or not entry[key] is None: 
                        if key and entry[key]:
                            pair.append({key:entry[key]}
                               )
                       cls.seen_value1.append(entry[key])
               
               if key == key2:
                   if not entry[key]:
                        continue
                   else:
                       if not entry[key] in cls.seen_value2 and entry[key] != "" or not entry[key] is None: 
                        if key and entry[key]:
                           pair.append({key:entry[key]}
                               )
                       cls.seen_value2.append(entry[key])
                       if pair:
                        cls._colec.append(pair)
                        pair = []
        return cls._colec

def check(cls,_value:str, 
              key1, key2,*,data:list) -> None:
        print(key1, key2)
        for val in _key_values(key1, key2, data):
            if val[0][key1] | val[1][key2] and (val[0][key1] | val[1][key2] == _value):
                cls._value_name1 = val[0][key1]
                cls._value_name2 = val[1][key2]
                return cls._value_name1, cls._value_name2
            else:
                if not cls._value_name1 and not cls._value_name2:
                    #cls._name_id = cls._id
                    print(f'No value foound for: {_value}!')


_value=""
key1=""
key2=""
data=[]

#print(check(_value,key1,key2,data=data))
