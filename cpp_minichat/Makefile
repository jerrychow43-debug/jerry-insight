CXX := g++
CXXFLAGS := -std=c++20 -Wall -Wextra -O2 -pthread

TARGET := minichat
SRC := src/main.cpp

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(TARGET)
	./$(TARGET) 19191

clean:
	rm -f $(TARGET)

