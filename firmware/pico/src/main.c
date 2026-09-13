//---------------------------------------------------------------------------
// INCLUDES
//--------------------------------------------------------------------------
#include "adc/adc.h"
#include "max/max14866.h"
#include "../external/pico_fast_serial/fast_serial.h"

//---------------------------------------------------------------------------
// GLOBALS
//--------------------------------------------------------------------------

typedef void (*command_func_t)(const char *args);

typedef struct
{
    const char *command_name;
    command_func_t func;
} command_t;

command_t command_list[] = {
    {"start acq", pulse_adc_trigger},
    {"write dac", dac},
    {"write mux", max14866},
    {"set mux", max14866_set},
    {"clear mux", max14866_clear},
    {"read", adc},
};

void process_command(char *input)
{
    char *command = strtok(input, " \r\n");
    char *subcommand = strtok(NULL, " \r\n");
    char *args = strtok(NULL, "\r\n");
    
    if (command != NULL && subcommand != NULL)
    {
        char full_command[50];
        snprintf(full_command, sizeof(full_command), "%s %s", command, subcommand);

        for (int i = 0; i < sizeof(command_list) / sizeof(command_t); i++)
        {
            if (strcmp(full_command, command_list[i].command_name) == 0)
            {
                if (args == NULL)
                {
                    args = "0";
                }
                command_list[i].func(args);
                return;
            }
        }
        printf("Unknown command: %s %s\n", command, subcommand);
    }
    else if (command != NULL)
    {
        for (int i = 0; i < sizeof(command_list) / sizeof(command_t); i++)
        {
            if (strcmp(command, command_list[i].command_name) == 0)
            {
                command_list[i].func(args);
                return;
            }
        }
        printf("Unknown command: %s\n", command);
    }
}

void read_input(char *buffer, int max_len)
{
    int len = fast_serial_read_until(buffer, max_len, '\n'); 
    
    if (len > 0) {
        buffer[len] = '\0';
        if (buffer[len - 1] == '\r') {
            buffer[len - 1] = '\0';
        }
    } else {
        buffer[0] = '\0';
    }
}


//---------------------------------------------------------------------------
// MAIN FUNCTION
//---------------------------------------------------------------------------

int main()
{
    fast_serial_init();

    while (!tud_mounted())
    {
        tud_task();
        tight_loop_contents();
    }
    
    sleep_ms(100);
    pio_adc_init();
    sleep_ms(100);
    dac_init();
    sleep_ms(100);
    max14866_init();
    sleep_ms(100);

    char input[128];
    while (true)
    {
        fast_serial_task();
        
        
        read_input(input, sizeof(input));
        if (input[0] != '\0')
        {
            process_command(input);
        }
    }
}
