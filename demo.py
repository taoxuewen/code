"""一个简单的 demo：演示函数、循环和命令行运行。"""


def fizzbuzz(n: int) -> list[str]:
    """返回 1..n 的 FizzBuzz 结果。"""
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return result


def main() -> None:
    print("Hello from code repo! 👋")
    for line in fizzbuzz(15):
        print(line)


if __name__ == "__main__":
    main()
