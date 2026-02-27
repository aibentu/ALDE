


entitie1: dict= {}
entitie2: dict= {}
table:list[dict] = [] 
matches: list = []
results: list = []
    

dictionary: list[dict[str, str | int]] = []

def add_to_dictionary(list:list[dict[str, str | int]]
                      ) -> list[dict[str, str | int]]:   
        return dictionary.append(list)

entitie1 = {
    "name": "Alice", 
    "sue`rname": "Smith",
    "occupation": "Engineer",
    "age": 30, 
    "city": "New York",
    "country": "USA"  
}
entitie2 = {
    "name": "John",
    "surname": "Doe",
    "occupation": "Manager",
    "age": 30,
    "city": "New York",
    "country": "USA",
    
}
table = [entitie1,entitie2]

query:list[dict[str, str | int]] = {"age": 30,
              "city": "New York",
              "country": "USA"
              }
print(f"Table to search: {table}")
print(f"Query to match: {query}")


def search_in_table(table: list[dict], query:list[
                     dict[str, str | int]]) -> list[dict[str, str | int]]:
    for entitie in table:
        for item in entitie:
            for queitem in query:
                if entitie[item] == query[queitem]:
                   matches.append({item:entitie[item]})
                if len(matches) == len(query):
                    if entitie not in results:
                         results.append(entitie)
    print(f"Match found for entities:{results} with query: {query} ")
    if len(results) == 0:
                print("No match found.")

search_in_table(table, query)
#print(add_to_dictionary(results))
