#include "foo.h"

#include <iostream>

void Foo::test_print(const std::string& to_print) {
    std::cout << to_print << std::endl;
}