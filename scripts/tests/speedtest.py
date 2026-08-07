import timeit

class Benchmark:
    def __init__(self):
        self.test_dictionary = {
            "test": [0 for _ in range(0, 2500000)],
            "test2": [0 for _ in range(0, 2500000)],
            "test3": [0 for _ in range(0, 2500000)],
            "test4": [0 for _ in range(0, 2500000)]
        }
        self.test_list = [0 for _ in range(0, 10000000)]

    def iterate_dictionary(self):
        for key, value in self.test_dictionary.items():
            for item in value:
                pass

    def iterate_list(self):
        for item in self.test_list:
            pass

if __name__ == "__main__":
    benchmark = Benchmark()

    dict_time = timeit.timeit(benchmark.iterate_dictionary, number=1)
    list_time = timeit.timeit(benchmark.iterate_list, number=1)

    print(f"Dictionary iteration time: {dict_time} seconds")
    print(f"List iteration time: {list_time} seconds")