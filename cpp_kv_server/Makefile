CXX := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -O2

TARGET := kv_server
SRC := src/main.cpp

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(TARGET)
	./$(TARGET) 6379

clean:
	rm -f $(TARGET)
